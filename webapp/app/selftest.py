"""
Reproducibility self-test.   python run.py selftest

Runs the real engine over a synthetic market built from a fixed seed, and
prints a SHA-256 of the resulting equity curve. Run it on both machines and
compare the hash: same hash means the two boxes compute identically, and any
remaining difference in the dashboard is coming from the DATA, not the code.

Why synthetic rather than a bundled data file
---------------------------------------------
A fixture of real prices would have to ship in the zip, would go stale, and
would still only prove the engine agrees on THAT data. numpy's PCG64 generator
is specified to produce identical streams on every platform, word size and
numpy version, so a seed is a better fixture than a file: nothing to ship,
nothing to keep current, and the inputs are provably identical on both boxes
before a single float is added.

The generated series is shaped to make the engine exercise its discrete
branches -- the ones that turn a 1e-15 difference into a visible one. It has
to produce Hurst gate flips (the sleeve turning on and off), volatility-brake
engagement, and per-asset cap hits, or the test would pass on two machines
that would still disagree on real data. run() asserts all three happened.

Two hashes are printed, and the ORDER matters
--------------------------------------------
INPUT is the gate. It covers the generated market, which depends on the app's
own universe and fixture parameters -- so two machines on different versions
produce different INPUTs and are not testing the same thing at all. Reporting
an arithmetic verdict in that situation points at the wrong suspect.

    INPUT differs
        different app version (or fixture). The COMBINED comparison is
        meaningless until this matches.
    INPUT matches, COMBINED differs
        check the app version FIRST anyway -- an engine change moves COMBINED
        while leaving INPUT untouched. Only with versions equal is this a
        genuine arithmetic difference, and then:
            different numpy/pandas       -> the fingerprint line
            different BLAS kernel        -> 'coretype' differs, or the box
                                            ignored OPENBLAS_CORETYPE
            different numpy SIMD         -> 'simd' differs
            different CPU arithmetic     -> x86-64 vs ARM
    both match
        the two compute identically; any dashboard difference is DATA.

`--expect <combined> --expect-input <input>` applies exactly that order and
exits 0 (match), 1 (arithmetic differs) or 2 (comparison invalid).
"""

from __future__ import annotations

import hashlib
import sys
import time

import numpy as np
import pandas as pd

from . import determinism, strategy as S

SEED = 20260814
N_BARS = 3000            # ~12 years; long enough for regime changes
START = "2012-01-03"


def make_market(seed: int = SEED) -> tuple[dict, pd.Series, pd.Series]:
    """A deterministic synthetic market with the statistical features the
    engine's branches depend on.

    Not trying to look like real prices -- trying to make every branch fire.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(START, periods=N_BARS)
    syms = S.TICKERS + [S.CASH_TICKER, S.LEVERAGE_SLEEVE, S.LEVERAGE3_SLEEVE]

    # A slow regime cycle drives BOTH volatility and drift, so calm uptrends
    # and violent selloffs alternate. That is what makes the vol brake engage
    # and disengage, and what makes the Hurst gate flip.
    t = np.arange(N_BARS)
    cycle = np.sin(2 * np.pi * t / 620.0) + 0.4 * np.sin(2 * np.pi * t / 190.0)
    vol = 0.006 + 0.011 * (1.0 + cycle) / 2.0          # 0.6%..1.7% daily
    drift = 0.00055 * cycle                             # trends both ways

    px = {}
    for i, sym in enumerate(syms):
        if sym == S.CASH_TICKER:
            # cash leg: a smooth, always-positive carry, like BIL
            close = 100.0 * np.exp(np.cumsum(np.full(N_BARS, 0.00006)))
        else:
            # each asset gets its own beta to the common factor plus its own
            # idiosyncratic noise, so the optimizer has something to choose
            beta = 0.5 + 0.15 * i
            common = rng.standard_normal(N_BARS)
            idio = rng.standard_normal(N_BARS)
            r = drift * beta + vol * (beta * common + idio) / np.sqrt(1 + beta ** 2)
            if sym in (S.LEVERAGE_SLEEVE, S.LEVERAGE3_SLEEVE):
                # mirror the real sleeve relationship: a daily-reset multiple
                # of the QQQ leg, so consolidation has something to convert
                mult = S.SLEEVE_LEVERAGE[sym]
                q = np.diff(np.log(px["QQQ"]["close"].to_numpy()), prepend=0.0)
                r = mult * q
            close = 100.0 * np.exp(np.cumsum(r))

        # OHLC around the close, deterministic and always ordered correctly
        span = np.abs(rng.standard_normal(N_BARS)) * 0.004 * close
        open_ = np.empty(N_BARS)
        open_[0] = close[0]
        open_[1:] = close[:-1] * (1.0 + 0.0004 * rng.standard_normal(N_BARS - 1))
        high = np.maximum(open_, close) + span
        low = np.minimum(open_, close) - span
        px[sym] = pd.DataFrame({"open": open_, "high": high, "low": low,
                                "close": close}, index=idx)

    # VIX tracks the vol cycle, so the regime switch (fast/normal/slow) fires
    vix = pd.Series(11.0 + 26.0 * (1.0 + cycle) / 2.0, index=idx)
    # 10-year yield sweeping through SIGD_RATE_REF, so the rate-tied Sortino
    # constant is sometimes zero and sometimes at its cap
    yld = pd.Series(0.005 + 0.055 * (1.0 + np.sin(2 * np.pi * t / 1500.0)) / 2.0,
                    index=idx)
    return px, vix, yld


def _app_version() -> str:
    """The shipped version string. Printed alongside the hashes because a
    version mismatch is the most likely reason two machines disagree, and it
    invalidates the comparison rather than merely explaining it."""
    try:
        from . import fixed_service
        return fixed_service.VERSION
    except Exception:
        return "?"


def _sha(a: np.ndarray) -> str:
    """Hash the exact bits. Little-endian float64 explicitly, so the digest
    does not depend on the machine's byte order."""
    return hashlib.sha256(
        np.ascontiguousarray(a, dtype="<f8").tobytes()).hexdigest()


def run(verbose: bool = True) -> dict:
    px, vix, yld = make_market()

    inputs = _sha(np.concatenate([px[s]["close"].to_numpy() for s in sorted(px)]))
    results = {}
    t0 = time.perf_counter()

    # One case per code path that can diverge: the plain book, a leveraged
    # sleeve (consolidation + a separate leg), and the brake switched off.
    cases = [
        ("base",       dict(sleeve_symbol="QQQ",  sleeve_frac=0.80,
                            vol_target=True,  vt_target=0.10)),
        ("leverage",   dict(sleeve_symbol="QLD",  sleeve_frac=0.60,
                            vol_target=True,  vt_target=0.12)),
        ("leverage3x", dict(sleeve_symbol="TQQQ", sleeve_frac=0.60,
                            vol_target=True,  vt_target=0.20)),
        ("nobrake",    dict(sleeve_symbol="QQQ",  sleeve_frac=0.80,
                            vol_target=False, vt_target=0.10)),
    ]
    quiet = lambda *a, **k: None
    branch_evidence = {"sleeve_flips": 0, "brake_engaged": 0, "cap_hits": 0}

    for name, kw in cases:
        res = S.run_backtest(px, vix, log_fn=quiet, long_yield=yld, **kw)
        eq = np.asarray(res.equity, float)
        results[name] = {
            "equity_sha256": _sha(eq),
            "final": float(eq[-1]),
            "adjustments": len(res.adjustments),
            "sleeve_on_bars": int(res.n_sleeve_on),
        }
        on = np.asarray(res.sleeve_on, bool)
        branch_evidence["sleeve_flips"] += int(np.abs(np.diff(on.astype(int))).sum())
        branch_evidence["brake_engaged"] += sum(
            1 for a in res.adjustments if a.get("vt", 1.0) < 0.999)
        branch_evidence["cap_hits"] += sum(
            1 for a in res.adjustments
            for w in a["weights"].values() if w >= S.MAX_WEIGHT - 1e-9)

    elapsed = time.perf_counter() - t0
    combined = hashlib.sha256(
        "".join(results[n]["equity_sha256"] for n, _ in cases).encode()
    ).hexdigest()

    out = {
        "input_sha256": inputs,
        "combined_sha256": combined,
        "cases": results,
        "seconds": round(elapsed, 1),
        "branches": branch_evidence,
        "environment": determinism.fingerprint(),
    }

    out["app_version"] = _app_version()

    if verbose:
        print()
        print("  Reproducibility self-test")
        print("  " + "-" * 66)
        print(f"  app {out['app_version']} | {determinism.summary_line()}")
        print()
        print(f"  1. INPUT      {inputs}")
        print(f"                (compare this FIRST -- see below)")
        print()
        for name, _ in cases:
            r = results[name]
            print(f"     {name:<12}   {r['equity_sha256'][:32]}  "
                  f"final {r['final']:>14,.4f}")
        print()
        print(f"  2. COMBINED   {combined}")
        print()
        print(f"  branches exercised: {branch_evidence['sleeve_flips']} sleeve "
              f"flips, {branch_evidence['brake_engaged']} braked rebalances, "
              f"{branch_evidence['cap_hits']} cap hits")
        print(f"  {elapsed:.1f}s")
        print()
        print("  Comparing with another machine -- check IN THIS ORDER:")
        print()
        print("  1. INPUT differs")
        print("       The two machines are not running the same version of")
        print("       this app, so they did not even test the same thing.")
        print("       The COMBINED comparison below is MEANINGLESS until this")
        print("       matches. Compare the `app` version on the line above and")
        print("       reinstall both from the same zip.")
        print()
        print("  2. INPUT matches, COMBINED differs")
        print("       Still check the `app` version first: an engine change")
        print("       (a new optimizer rule, say) moves COMBINED while leaving")
        print("       INPUT untouched. Only once the versions agree does this")
        print("       mean a genuine arithmetic difference -- then compare the")
        print("       environment line: numpy, pandas, coretype, simd.")
        print()
        print("  3. Both match")
        print("       The two compute identically. Any difference you see on")
        print("       the dashboard is DATA, not code.")
        print()
        print("  Or let it do the comparison for you:")
        print(f"       python run.py selftest --expect {combined[:16]}... \\")
        print(f"                              --expect-input {inputs[:16]}...")
        print()

    # The test is worthless if the branches never fired -- it would pass on two
    # machines that still disagree on real data. Fail loudly instead.
    if branch_evidence["sleeve_flips"] < 2:
        raise SystemExit("SELFTEST INVALID: the sleeve never toggled, so the "
                         "Hurst gate was not exercised.")
    if branch_evidence["brake_engaged"] < 1:
        raise SystemExit("SELFTEST INVALID: the volatility brake never "
                         "engaged, so the path-dependent branch that caused "
                         "the original Linux/Windows split was not exercised.")
    return out


def _flag(argv, name):
    """--name VALUE, or --name=VALUE. Returns None when absent."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1].strip().rstrip(".")
        if a.startswith(name + "="):
            return a.split("=", 1)[1].strip().rstrip(".")
    return None


def _matches(actual: str, expected: str) -> bool:
    """Prefix comparison, so a value copied from the printed summary (which
    abbreviates) compares equal to the full digest."""
    e = (expected or "").strip().lower().rstrip(".")
    return bool(e) and actual.lower().startswith(e)


def main(argv=None) -> int:
    """Exit code: 0 all good, 1 arithmetic differs, 2 comparison invalid."""
    argv = sys.argv[1:] if argv is None else argv
    want_comb = _flag(argv, "--expect")
    want_in = _flag(argv, "--expect-input")
    out = run(verbose=True)
    if "--json" in argv:
        import json
        print(json.dumps(out, indent=1))

    if not (want_comb or want_in):
        return 0

    # Inputs are the gate. If the two machines did not test the same thing,
    # saying anything about the arithmetic is worse than saying nothing -- it
    # points at the wrong suspect, which is exactly what happened once.
    if want_in and not _matches(out["input_sha256"], want_in):
        print("  RESULT: INPUTS DIFFER -- comparison invalid.")
        print(f"    expected input {want_in}")
        print(f"    got            {out['input_sha256'][:len(want_in)]}")
        print("    The two machines are not running the same version of this")
        print(f"    app. This one is {out['app_version']}. Reinstall both from")
        print("    the same zip, then compare again.")
        print()
        return 2
    if want_comb and not _matches(out["combined_sha256"], want_comb):
        print("  RESULT: inputs match, ARITHMETIC DIFFERS.")
        print(f"    expected {want_comb}")
        print(f"    got      {out['combined_sha256'][:len(want_comb)]}")
        if not want_in:
            print("    NOTE: no --expect-input given, so an input mismatch")
            print("    cannot be ruled out. Pass it to be sure this is really")
            print("    an arithmetic difference.")
        print(f"    Check the app version ({out['app_version']}) on both")
        print("    machines first -- an engine change moves this hash. If the")
        print("    versions agree, compare the environment line above.")
        print()
        return 1
    print("  RESULT: MATCH -- the two machines compute identically.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
