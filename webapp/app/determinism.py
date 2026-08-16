"""
Reproducibility controls.  MUST be imported before numpy, anywhere.

Why this file exists
--------------------
The same code, on the same data, produced a different equity curve on Linux
and on Windows. It was not a Windows problem. Measured here, on ONE machine,
changing nothing but the BLAS kernel:

    OPENBLAS_CORETYPE=Haswell   final equity 1,564,873.7355676291
    OPENBLAS_CORETYPE=Nehalem   final equity 1,565,333.7623422896

numpy's `@` operator dispatches to OpenBLAS, which is built DYNAMIC_ARCH: it
picks its matmul microkernel AT RUNTIME from the detected CPU. Different
kernels use different blocking factors, so they sum the same products in a
different order. Floating-point addition is not associative, so the results
differ in the last bit or two (~1e-15 relative).

That alone would be harmless. It is not harmless HERE because of the OPTIMIZER.
optimize_weights runs N_RESTARTS = 5 gradient ascents from different starting
points and keeps the best by a strict float comparison:

        if cur_obj > best_obj:

When two restarts converge to near-equal objective values -- which is common,
because restart 0 anchors on the previous weights and usually lands close to
the global optimum -- a last-bit difference in the objective selects a
DIFFERENT LOCAL OPTIMUM. Not a nearby weight vector: a different one. That
happens at a rebalance, of which there are ~600, and the resulting book
difference is thousands of times larger than the floating-point difference
that caused it.

This was measured rather than reasoned, and the measurement corrected an
earlier guess. Running the identical backtest under two BLAS kernels and
ablating one mechanism at a time (relative difference in final equity):

    production                                    4.97e-04
    volatility brake disabled entirely            4.62e-04   <- no effect
    continuous brake (no threshold jump)          5.07e-04   <- no effect
    continuous sleeve (no on/off flip)            5.77e-04   <- no effect
    N_RESTARTS = 1 (no argmax over restarts)      6.03e-08   <- THE cause

The volatility brake IS path dependent -- _vt_scale reads the strategy's own
trailing realised volatility -- and that looked like the obvious culprit. It
is not: removing it entirely leaves the divergence essentially unchanged.
Smoothing the discrete branches does not help either, because the restart
argmax is not a threshold that can be smoothed; it is a choice between
distinct solutions. Pinning dispatch is the fix, which is what this file does.

Two independent dispatch layers therefore have to be pinned, because each one
changes the answer on its own:

  1. OpenBLAS kernel selection  -> OPENBLAS_CORETYPE
  2. numpy's own SIMD dispatch  -> NPY_DISABLE_CPU_FEATURES
     (numpy compiles several SIMD variants of its reduction loops and picks one
     per CPU; the number of partial accumulators differs, so the summation
     order differs. Disabling everything above the universal x86-64 baseline
     makes every x86-64 machine take the same path.)

Thread counts are pinned too. At this problem's matrix sizes OpenBLAS stays
single-threaded anyway, so it costs nothing and removes one more variable.

The two knobs behave differently when they cannot be honoured, which is why
_probe() exists:

  * OPENBLAS_CORETYPE fails soft. An unknown core name is ignored and BLAS
    auto-detects, so the app still runs -- it just may not match.
  * NPY_DISABLE_CPU_FEATURES fails HARD, and only for names in that wheel's
    compile-time baseline. numpy raises at import, and it cannot be
    re-imported afterwards ("cannot load module more than once per process"),
    so there is no retrying in place. _probe() measures the real list in a
    subprocess first rather than guessing it.

None of this is assumed to have worked. `python run.py selftest` measures the
result and prints a hash to compare between machines, and fingerprint()
reports what was actually achieved rather than what was requested.

Everything here is skipped if the variable is already set, so an operator can
override any of it from the environment without editing code.
"""

from __future__ import annotations

import os
import platform
import re as _re
import sys

# The BLAS microkernel every machine will be asked to use. Nehalem needs only
# SSE4.2 (Intel 2008+, AMD 2011+), so effectively every x86-64 CPU in service
# can run it. A newer kernel would be marginally faster on big matrices; this
# app's are (252x10)@(10x22), far too small for that to show up -- measured at
# 12.3s vs 11.5s for a full backtest, against 13.7s unpinned.
#
# Not applicable on ARM (Apple Silicon, Graviton): OpenBLAS uses different
# core names there, the value is ignored, and the selftest will report a
# different hash than an x86-64 box. That is honest rather than hidden.
CORETYPE = "Nehalem"

# Everything numpy may dispatch to above the x86-64 baseline. A superset
# spanning several numpy releases on purpose: the dispatch names changed
# between 1.x and 2.x, and a name the installed numpy does not know is simply
# ignored.
#
# Names that ARE part of that wheel's compile-time baseline are a different
# matter -- numpy raises RuntimeError at import rather than ignoring them, and
# which names those are depends on how the wheel was built (numpy 2.x
# manylinux baselines on X86_V2, older wheels on SSE3). So the list cannot be
# correct for every environment, and import_numpy() below negotiates it down
# instead of guessing.
NUMPY_DISABLE = (
    "X86_V3 X86_V4 "
    "SSE41 SSE42 POPCNT AVX F16C FMA3 AVX2 "
    "AVX512F AVX512CD AVX512_KNL AVX512_KNM AVX512_SKX "
    "AVX512_CLX AVX512_CNL AVX512_ICL AVX512_SPR"
)

_THREAD_VARS = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)

# What we actually set, for the fingerprint. Populated by apply().
_applied: dict[str, str] = {}
_already: dict[str, str] = {}
# set when the SIMD probe could not run and the static fallback list was
# used instead. Reported in the fingerprint so it is never silent.
_rejected: list[str] = []


def apply() -> None:
    """Pin every dispatch knob. Safe to call more than once; a no-op after the
    first call, and never overrides a value the operator already set."""
    if _applied or _already:
        return
    if "numpy" in sys.modules:
        # Not fatal -- but the settings below only take effect at numpy import,
        # so say so loudly rather than silently producing unreproducible runs.
        print("WARNING: app.determinism imported after numpy; dispatch is "
              "already fixed for this process and results may not be "
              "reproducible. Import app (or app.determinism) first.",
              file=sys.stderr)

    wanted = {v: "1" for v in _THREAD_VARS}
    wanted["OPENBLAS_CORETYPE"] = CORETYPE

    # Disable exactly what THIS numpy dispatches at runtime -- measured, not
    # guessed, so no baseline name can end up in the list and abort the
    # import. Fall back to the static superset only if the probe could not
    # run; that list has the known-baseline names stripped, so it is safe for
    # current wheels even though it is less precise.
    probe = _probe()
    if probe["ok"] and probe["dispatch"]:
        wanted["NPY_DISABLE_CPU_FEATURES"] = " ".join(probe["dispatch"])
    else:
        baseline = set(probe.get("baseline") or ["X86_V2"])
        wanted["NPY_DISABLE_CPU_FEATURES"] = " ".join(
            f for f in NUMPY_DISABLE.split() if f not in baseline)
        _rejected.append("probe-failed")

    for k, v in wanted.items():
        if os.environ.get(k):
            _already[k] = os.environ[k]      # operator override; leave it
        else:
            os.environ[k] = v
            _applied[k] = v


_PROBE = ("from numpy._core import _multiarray_umath as m\n"
          "import numpy\n"
          "print(numpy.__version__)\n"
          "print(' '.join(m.__cpu_baseline__))\n"
          "print(' '.join(m.__cpu_dispatch__))\n")

_PROBE_OLD = ("from numpy.core import _multiarray_umath as m\n"
              "import numpy\n"
              "print(numpy.__version__)\n"
              "print(' '.join(m.__cpu_baseline__))\n"
              "print(' '.join(m.__cpu_dispatch__))\n")

_probe_result: dict[str, object] = {}


def _probe() -> dict:
    """Ask the installed numpy, in a clean subprocess, which SIMD features it
    compiled into its baseline and which it dispatches at runtime.

    This has to be a subprocess. The disable list is only read at numpy's
    first import, and getting it wrong raises:

        RuntimeError: You cannot disable CPU feature 'X86_V2', since it is
        part of the baseline optimizations

    -- and numpy cannot be re-imported after that ("cannot load module more
    than once per process"), so there is no retry-in-place. Which names are
    baseline depends on how the wheel was built, so it must be measured
    rather than assumed. Costs ~0.1s, once per process.

    The subprocess runs with the pinning variables REMOVED, so it reports the
    machine's real capability rather than what we just asked for.
    """
    if _probe_result:
        return _probe_result
    out = {"ok": False, "numpy": "", "baseline": [], "dispatch": []}
    if not sys.executable:
        _probe_result.update(out)
        return out
    env = dict(os.environ)
    for k in ("NPY_DISABLE_CPU_FEATURES", "OPENBLAS_CORETYPE"):
        env.pop(k, None)
    for code in (_PROBE, _PROBE_OLD):          # numpy 2.x path, then 1.x path
        try:
            import subprocess
            r = subprocess.run([sys.executable, "-c", code], env=env,
                               capture_output=True, text=True, timeout=120)
        except Exception:
            break
        if r.returncode == 0:
            lines = r.stdout.strip().splitlines()
            if len(lines) >= 3:
                out = {"ok": True, "numpy": lines[0].strip(),
                       "baseline": lines[1].split(), "dispatch": lines[2].split()}
            break
    _probe_result.update(out)
    return out


def import_numpy():
    """Import numpy after the settings are in place. Kept as the single entry
    point so the ordering rule lives in one file."""
    import numpy
    return numpy


def fingerprint() -> dict:
    """Everything that can change a number, in one dict.

    Stamped into the cached payloads and printed by the selftest, so a curve
    can always be attributed to the environment that produced it. If two
    machines disagree, diffing this says which layer to look at.
    """
    out = {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "coretype": os.environ.get("OPENBLAS_CORETYPE", ""),
        "numpy_disabled": os.environ.get("NPY_DISABLE_CPU_FEATURES", ""),
        "threads": os.environ.get("OPENBLAS_NUM_THREADS", ""),
        "overridden": sorted(_already),
        "simd_pin_fallback": list(_rejected),
    }
    try:
        import numpy as np
        out["numpy"] = np.__version__
        # Which SIMD paths numpy ended up with AFTER our disable list. This is
        # the value that matters -- the request above is only a request.
        try:
            from numpy._core import _multiarray_umath as _mu
            feats = getattr(_mu, "__cpu_features__", {})
            out["numpy_baseline"] = list(getattr(_mu, "__cpu_baseline__", []))
            out["numpy_dispatch_active"] = sorted(
                f for f in getattr(_mu, "__cpu_dispatch__", []) if feats.get(f))
        except Exception:
            out["numpy_baseline"] = out["numpy_dispatch_active"] = ["?"]
    except Exception:
        out["numpy"] = "?"
    try:
        import pandas as pd
        out["pandas"] = pd.__version__
    except Exception:
        out["pandas"] = "?"
    return out


def summary_line() -> str:
    fp = fingerprint()
    return (f"python {fp['python']} | numpy {fp['numpy']} | "
            f"pandas {fp['pandas']} | {fp['platform']} | "
            f"coretype {fp['coretype'] or 'auto'} | "
            f"simd {','.join(fp.get('numpy_dispatch_active') or []) or 'baseline only'}")
