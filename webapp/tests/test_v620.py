"""
Tests for the v6.2.0-6.2.2 changes: reproducibility, config resolution, the
launcher's venv detection, and the scheduler's cache-age logic.

Run:  python run.py selftest        (the reproducibility check proper)
      .venv/bin/python -m unittest discover tests

Deliberately fast -- nothing here runs a backtest except one small
make_market() call. The expensive end-to-end check is `run.py selftest`,
which is a user-facing command rather than a test, because its value is in
being run on TWO machines and compared.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app                                    # noqa: E402  applies the pinning
from app import determinism                   # noqa: E402


class TestDeterminismKnobs(unittest.TestCase):
    def test_apply_is_idempotent(self):
        before = dict(os.environ)
        determinism.apply()
        determinism.apply()
        self.assertEqual(os.environ.get("OPENBLAS_CORETYPE"),
                         before.get("OPENBLAS_CORETYPE"))

    def test_never_overrides_an_operator_setting(self):
        """A value already in the environment must survive untouched -- that is
        the escape hatch for a machine where the pinned kernel is wrong."""
        code = ("import os, sys; sys.path.insert(0, %r);"
                "import app;"
                "print(os.environ['OPENBLAS_CORETYPE'])" % str(ROOT))
        env = dict(os.environ, OPENBLAS_CORETYPE="Haswell")
        out = subprocess.run([sys.executable, "-c", code], env=env,
                             capture_output=True, text=True, timeout=180)
        self.assertEqual(out.stdout.strip(), "Haswell", out.stderr)

    def test_disable_list_excludes_baseline(self):
        """The list handed to numpy must contain no baseline feature, or numpy
        raises at import and the app will not start at all."""
        probe = determinism._probe()
        if not probe["ok"]:
            self.skipTest("SIMD probe unavailable here")
        disabled = set(os.environ.get("NPY_DISABLE_CPU_FEATURES", "").split())
        self.assertFalse(disabled & set(probe["baseline"]),
                         "baseline feature in the disable list would abort "
                         "numpy's import")

    def test_no_simd_left_active(self):
        """The point of the exercise: after pinning, numpy should be running
        its baseline code path only, so two different CPUs take the same one."""
        fp = determinism.fingerprint()
        if fp.get("overridden") or fp.get("simd_pin_fallback"):
            self.skipTest("environment overrides in play")
        self.assertEqual(fp["numpy_dispatch_active"], [])

    def test_fingerprint_reports_versions(self):
        fp = determinism.fingerprint()
        for key in ("python", "numpy", "pandas", "platform", "coretype"):
            self.assertTrue(fp.get(key), f"{key} missing from fingerprint")


class TestSelftestFixture(unittest.TestCase):
    def test_market_is_reproducible(self):
        """The fixture is the foundation of the whole check: if two calls
        differed, a hash mismatch between machines would prove nothing."""
        from app.selftest import make_market
        a, _, _ = make_market()
        b, _, _ = make_market()
        for sym in a:
            self.assertTrue((a[sym]["close"] == b[sym]["close"]).all(), sym)

    def test_ohlc_is_well_formed(self):
        """high >= max(open, close) and low <= min(open, close) everywhere, or
        the Heikin-Ashi trend candle is being fed nonsense."""
        from app.selftest import make_market
        px, _, _ = make_market()
        for sym, df in px.items():
            self.assertTrue((df["high"] >= df[["open", "close"]].max(axis=1)).all(), sym)
            self.assertTrue((df["low"] <= df[["open", "close"]].min(axis=1)).all(), sym)
            self.assertTrue((df["close"] > 0).all(), sym)


class TestSelftestComparison(unittest.TestCase):
    """v6.3.0: the comparison must check INPUTS before arithmetic.

    Reported from another session: a differing COMBINED hash sent the reader
    to the environment line, when the two machines were actually running
    different versions and had not tested the same thing at all.
    """

    def _out(self, combined="b" * 64, inputs="a" * 64, version="v9.9.9"):
        return {"combined_sha256": combined, "input_sha256": inputs,
                "app_version": version}

    def _main(self, argv, out):
        """Run selftest.main with run() stubbed, capturing what it prints."""
        import io, contextlib
        from app import selftest
        real = selftest.run
        buf = io.StringIO()
        try:
            selftest.run = lambda verbose=True: out
            with contextlib.redirect_stdout(buf):
                code = selftest.main(argv)
        finally:
            selftest.run = real
        return code, buf.getvalue()

    def test_input_mismatch_is_reported_before_arithmetic(self):
        """Inputs are the gate: a wrong COMBINED must NOT be blamed on the
        environment when the inputs did not even match."""
        code, text = self._main(
            ["--expect", "c" * 64, "--expect-input", "d" * 64], self._out())
        self.assertEqual(code, 2)
        self.assertIn("INPUTS DIFFER", text)
        self.assertIn("version", text.lower())
        self.assertNotIn("ARITHMETIC DIFFERS", text)

    def test_arithmetic_mismatch_names_the_version_first(self):
        code, text = self._main(
            ["--expect", "c" * 64, "--expect-input", "a" * 64], self._out())
        self.assertEqual(code, 1)
        self.assertIn("ARITHMETIC DIFFERS", text)
        self.assertLess(text.index("version"), text.index("environment"),
                        "version must be checked before the environment line")

    def test_match_exits_zero(self):
        code, text = self._main(
            ["--expect", "b" * 64, "--expect-input", "a" * 64], self._out())
        self.assertEqual(code, 0)
        self.assertIn("MATCH", text)

    def test_expect_without_input_says_it_cannot_rule_inputs_out(self):
        code, text = self._main(["--expect", "c" * 64], self._out())
        self.assertEqual(code, 1)
        self.assertIn("cannot be ruled out", text)

    def test_no_flags_is_a_plain_run(self):
        code, _ = self._main([], self._out())
        self.assertEqual(code, 0)

    def test_abbreviated_hashes_compare_equal(self):
        """The summary abbreviates, so a value pasted from it must work."""
        code, _ = self._main(
            ["--expect", "bbbbbbbbbbbbbbbb...", "--expect-input", "aaaaaaaaaaaaaaaa"],
            self._out())
        self.assertEqual(code, 0)

    def test_version_is_in_the_payload(self):
        from app import selftest
        self.assertTrue(selftest._app_version())


class TestConfig(unittest.TestCase):
    """settings.py is imported once per process, so these run it in
    subprocesses with different config files rather than trying to reload."""

    def _probe(self, ini: str, env=None, expr="settings.PORT"):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            # a throwaway project dir with only what settings.py reads
            proj = Path(td)
            (proj / "config.ini").write_text(ini, encoding="utf-8")
            code = (
                "import sys, pathlib;"
                f"sys.path.insert(0, {str(ROOT)!r});"
                "import app.settings as settings;"
                f"settings.CONFIG_PATH = pathlib.Path({str(proj / 'config.ini')!r});"
                "settings._file_cfg = settings._load_config_ini();"
                "import importlib;"
                f"print({expr})"
            )
            e = dict(os.environ)
            e.pop("MW_PORT", None)
            e.update(env or {})
            r = subprocess.run([sys.executable, "-c", code], env=e,
                               capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout.strip()

    def test_reads_a_plain_value(self):
        out = self._probe("[marketwatch]\nport = 8123\n",
                          expr="settings.cfg('MW_PORT')")
        self.assertEqual(out, "8123")

    def test_accepts_the_prefixed_spelling_too(self):
        out = self._probe("[marketwatch]\nmw_port = 8124\n",
                          expr="settings.cfg('MW_PORT')")
        self.assertEqual(out, "8124")

    def test_strips_a_trailing_comment(self):
        """configparser does NOT strip inline comments by default, and a key
        with '# my key' appended would otherwise be sent to FRED verbatim."""
        out = self._probe("[marketwatch]\nfred_api_key = abc123  # my key\n",
                          expr="repr(settings.cfg('MW_FRED_API_KEY'))")
        self.assertEqual(out, "'abc123'")

    def test_percent_sign_is_literal(self):
        """interpolation=None, or a key containing % raises InterpolationError
        and the whole app fails to import."""
        out = self._probe("[marketwatch]\nadmin_token = ab%cd\n",
                          expr="settings.cfg('MW_ADMIN_TOKEN')")
        self.assertEqual(out, "ab%cd")

    def test_utf8_is_read_as_utf8(self):
        """Windows would otherwise decode with the locale codepage."""
        out = self._probe("[marketwatch]\nadmin_token = café\n",
                          expr="settings.cfg('MW_ADMIN_TOKEN')")
        self.assertEqual(out, "café")

    def test_config_file_beats_the_environment(self):
        """v6.2.2 precedence: what is written in config.ini wins. A stale
        MW_* left in a shell profile or a Windows user variable must not
        silently override the key you just pasted into the file."""
        out = self._probe("[marketwatch]\nport = 8123\n",
                          env={"MW_PORT": "9999"},
                          expr="settings.cfg('MW_PORT')")
        self.assertEqual(out, "8123")

    def test_environment_still_fills_an_empty_setting(self):
        """Precedence is flipped, not removed: an EMPTY key in the file must
        fall through to the environment rather than shadow it with ''."""
        out = self._probe("[marketwatch]\nport =\n",
                          env={"MW_PORT": "9999"},
                          expr="settings.cfg('MW_PORT')")
        self.assertEqual(out, "9999")

    def test_conflict_is_reported(self):
        out = self._probe("[marketwatch]\nport = 8123\n",
                          env={"MW_PORT": "9999"},
                          expr="settings.config_source('MW_PORT')")
        self.assertIn("ignored", out)

    def test_utf8_bom_from_windows_notepad(self):
        """Notepad's 'Save as UTF-8' writes a BOM. Read as plain utf-8,
        configparser raises MissingSectionHeaderError and EVERY setting --
        including the FRED key -- silently reverts to its default."""
        import tempfile, pathlib as _pl
        with tempfile.TemporaryDirectory() as td:
            ini = _pl.Path(td) / "config.ini"
            ini.write_bytes(b"\xef\xbb\xbf[marketwatch]\nfred_api_key = abc123\n")
            code = ("import sys, pathlib;"
                    f"sys.path.insert(0, {str(ROOT)!r});"
                    "import app.settings as s;"
                    f"s.CONFIG_PATH = pathlib.Path({str(ini)!r});"
                    "s._file_cfg = s._load_config_ini();"
                    "print(s.cfg('MW_FRED_API_KEY'))")
            r = subprocess.run([sys.executable, "-c", code],
                               capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "abc123")

    def test_missing_file_is_not_fatal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            code = ("import sys, pathlib;"
                    f"sys.path.insert(0, {str(ROOT)!r});"
                    "import app.settings as s;"
                    f"s.CONFIG_PATH = pathlib.Path({str(Path(td) / 'nope.ini')!r});"
                    "print(s._load_config_ini())")
            r = subprocess.run([sys.executable, "-c", code],
                               capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "{}")


class TestRestartTieBreak(unittest.TestCase):
    """The v6.2.2 optimizer tie-break."""

    def test_first_restart_always_wins(self):
        """Regression. best_obj starts at -inf and -inf + margin is NaN, so a
        naive margin test returns False for every candidate and w_prev wins
        permanently -- freezing the optimizer. It cost 3.5x of final equity,
        and it looks like a perfect reproducibility result while doing it."""
        import numpy as np
        from app import strategy as S
        w = np.full(S.N_DIMS, 1.0 / S.N_DIMS)
        self.assertTrue(S._restart_wins(-5.0, w, -np.inf, w.copy(), w, True))

    def test_clear_winner_still_wins(self):
        import numpy as np
        from app import strategy as S
        w_prev = np.full(S.N_DIMS, 1.0 / S.N_DIMS)
        far = np.zeros(S.N_DIMS); far[S.IDX_CASH] = 1.0
        # far is worse on the stability key but much better on the objective
        self.assertTrue(S._restart_wins(2.0, far, 1.0, w_prev, w_prev, True))
        self.assertFalse(S._restart_wins(1.0, far, 2.0, w_prev, w_prev, True))

    def test_tie_goes_to_the_book_already_held(self):
        import numpy as np
        from app import strategy as S
        w_prev = np.full(S.N_DIMS, 1.0 / S.N_DIMS)
        near = w_prev.copy()
        far = np.zeros(S.N_DIMS); far[S.IDX_CASH] = 1.0
        obj = 1.0
        tie = obj * (1.0 + S.RESTART_TIE_REL / 10.0)     # inside the margin
        self.assertTrue(S._restart_wins(tie, near, obj, far, w_prev, True))
        self.assertFalse(S._restart_wins(tie, far, obj, near, w_prev, True))

    def test_second_tie_break_prefers_spy_and_qqq(self):
        import numpy as np
        from app import strategy as S
        w_prev = np.zeros(S.N_DIMS); w_prev[S.IDX_CASH] = 1.0
        a = np.zeros(S.N_DIMS); a[S.IDX_SPY] = 0.5; a[S.IDX_CASH] = 0.5
        b = np.zeros(S.N_DIMS); b[2] = 0.5; b[S.IDX_CASH] = 0.5
        # identical L1 distance from w_prev; a holds SPY, b does not
        self.assertEqual(float(np.abs(a - w_prev).sum()),
                         float(np.abs(b - w_prev).sum()))
        self.assertTrue(S._restart_wins(1.0, a, 1.0, b, w_prev, True))
        self.assertFalse(S._restart_wins(1.0, b, 1.0, a, w_prev, True))

    def test_margin_is_narrow(self):
        """Widening it backfires -- measured 3.5x WORSE than production at
        1e-4, because 'inside the margin' is itself a noisy threshold."""
        from app import strategy as S
        self.assertLessEqual(S.RESTART_TIE_REL, 1e-5)


class TestLauncher(unittest.TestCase):
    """These inspect run.py's AST rather than its text.

    Scanning the source as a string matches the COMMENTS too -- including the
    comment that documents the very bug being tested for, which makes the test
    pass or fail for the wrong reason. Parse the code and look at the code.
    """

    @staticmethod
    def _tree():
        import ast
        return ast.parse((ROOT / "run.py").read_text(encoding="utf-8"))

    @staticmethod
    def _func(tree, name):
        import ast
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"{name}() not found in run.py")

    def _attrs_used(self, name):
        """`sys.X` attribute names actually referenced in a function's code,
        with the docstring excluded."""
        import ast
        fn = self._func(self._tree(), name)
        body = fn.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]          # drop the docstring
        out = set()
        for stmt in body:
            for node in ast.walk(stmt):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "sys"):
                    out.add(node.attr)
        return out

    def test_in_venv_uses_prefix_not_executable(self):
        """Regression test. .venv/bin/python is a SYMLINK to the system
        interpreter on Linux, so comparing resolved sys.executable made
        in_venv() return True from OUTSIDE the venv -- which silently ran the
        app against the system's numpy and defeated the version pinning."""
        used = self._attrs_used("in_venv")
        self.assertIn("prefix", used)
        self.assertNotIn("executable", used,
                         "sys.executable resolves through the venv symlink")

    def test_documented_commands_match_the_code(self):
        """Requirement (2): the same commands on both systems. The nearest
        thing to a machine-checkable version is that the commands the module
        docstring advertises are exactly the ones that exist, on any platform
        -- COMMANDS is a plain module-level dict with no os.name branching."""
        import ast, re
        tree = self._tree()
        documented = set(re.findall(r"python run\.py (\w+)", ast.get_docstring(tree)))
        implemented = set()
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", "") == "COMMANDS" for t in node.targets)):
                self.assertIsInstance(node.value, ast.Dict)
                implemented = {k.value for k in node.value.keys}
        # `serve` is the no-argument default, so it is not spelled out
        self.assertEqual(documented | {"serve"}, implemented)

    def test_pip_upgrade_is_conditional_and_verified(self):
        """pip upgrading ITSELF mid-run corrupted an install here before: it
        left a half-replaced pip that could not import. v6.2.5 reintroduces
        the upgrade, but ONLY for a pip too old to read modern wheel tags --
        so it must be guarded by a version test and followed by a check."""
        import ast
        src = (ROOT / "run.py").read_text(encoding="utf-8")
        tree = self._tree()
        upgrades = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in node.args:
                if not isinstance(arg, ast.List):
                    continue
                strs = [e.value for e in arg.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if "pip" in strs and "install" in strs and "--upgrade" in strs:
                    upgrades.append(strs)
        # at most the one guarded upgrade, and never on the requirements install
        self.assertLessEqual(len(upgrades), 1)
        for strs in upgrades:
            self.assertNotIn("-r", strs,
                             "the requirements install must not carry --upgrade")
        fn = self._func(tree, "ensure_venv")
        body = ast.dump(fn)
        self.assertIn("_pip_version", body,
                      "the upgrade must be gated on pip's version")
        self.assertIn("_pip_works", body,
                      "and verified afterwards")

    def test_missing_wheel_fails_before_a_compiler_is_needed(self):
        """A pinned version with no wheel for the running Python used to fall
        through to a source build and die in meson with 'Unknown compiler'.
        The first install pass must refuse source builds so the real reason
        surfaces instead."""
        import ast
        found = False
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value == "--only-binary=:all:":
                    found = True
        self.assertTrue(found, "first pip pass should pass --only-binary=:all:")


class TestRequirements(unittest.TestCase):
    """Guards for the v6.2.3 dependency fix."""

    @staticmethod
    def _run_mod():
        import importlib.util
        spec = importlib.util.spec_from_file_location("runmod", ROOT / "run.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_no_unconditional_pin_of_a_distutils_package(self):
        """pandas-datareader 0.10.0 imports distutils, removed from the stdlib
        in Python 3.12. Pinned without a marker it installs cleanly and then
        fails at import -- which is exactly how it shipped."""
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        lines = [l.split("#")[0].strip() for l in req.splitlines()]
        bare = [l for l in lines if l.startswith("pandas-datareader==")
                and ";" not in l]
        self.assertEqual(bare, [], "pandas-datareader needs a python_version "
                                   "marker on every pin")

    def test_marker_selects_the_right_version(self):
        """The parser used by _deps_ok must evaluate the marker, or the
        version check either always fails (endless reinstall) or silently
        skips the package."""
        import re
        mod = self._run_mod()
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        chosen = []
        for line in req.splitlines():
            line = line.split("#")[0].strip()
            m = re.match(mod._REQ_RE, line)
            if m and m.group(1) == "pandas-datareader":
                chosen.append((m.group(2).strip(), m.group(3)))
        self.assertEqual(len(chosen), 2, "expected one pin per interpreter range")
        versions = {v for v, _ in chosen}
        self.assertEqual(versions, {"0.11.1", "0.10.0"})

    def test_deps_ok_does_not_demand_a_reinstall(self):
        """A marker the parser mishandles makes _deps_ok always False, so the
        launcher reinstalls every single start."""
        mod = self._run_mod()
        if not mod.VENV_PY.exists():
            self.skipTest("no venv here")
        self.assertTrue(mod._deps_ok())

    def test_setup_verifies_imports_not_just_installs(self):
        """Resolving a wheel is not the same as importing it."""
        import ast
        tree = ast.parse((ROOT / "run.py").read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
        self.assertIn("_imports_ok", names)
        body = ast.dump(ast.parse(
            (ROOT / "run.py").read_text(encoding="utf-8")))
        self.assertIn("_imports_ok", body)


class TestScheduleTimezone(unittest.TestCase):
    """v6.2.8: the schedule hour belongs to a named zone, not the host clock."""

    def test_cron_uses_the_configured_zone(self):
        """A UTC server and a local desktop running the same config fired five
        hours apart -- 06:20 UTC vs 06:20 America/Chicago. Naming a zone has
        to make the trigger ignore the host clock."""
        from zoneinfo import ZoneInfo
        from apscheduler.triggers.cron import CronTrigger
        import datetime
        tz = ZoneInfo("America/Chicago")
        base = datetime.datetime(2026, 8, 15, 3, 0, tzinfo=datetime.timezone.utc)
        nxt = CronTrigger(hour=6, minute=20, timezone=tz).get_next_fire_time(None, base)
        self.assertEqual(nxt.astimezone(tz).hour, 6)
        self.assertEqual(nxt.astimezone(tz).minute, 20)
        # 06:20 CDT is 11:20 UTC -- NOT 06:20 UTC
        self.assertEqual(nxt.astimezone(datetime.timezone.utc).hour, 11)

    def test_bad_zone_falls_back_instead_of_crashing(self):
        from app import settings
        old = settings.UPDATE_TIMEZONE
        try:
            settings.UPDATE_TIMEZONE = "Not/AZone"
            self.assertIsNone(settings.update_tzinfo())
        finally:
            settings.UPDATE_TIMEZONE = old

    def test_empty_zone_means_local(self):
        from app import settings
        old = settings.UPDATE_TIMEZONE
        try:
            settings.UPDATE_TIMEZONE = ""
            self.assertIsNone(settings.update_tzinfo())
        finally:
            settings.UPDATE_TIMEZONE = old

    def test_next_update_display_uses_the_minute(self):
        """Regression: the browser hardcoded minute 0 while the schedule runs
        at :20, so every 'next update' stamp was 20 minutes early."""
        js = (ROOT / "static" / "strategy.js").read_text(encoding="utf-8")
        i = js.index("function nextUpdateAt()")
        body = js[i:js.index("function nextUpdateText()")]
        self.assertIn("updateMinute", body)
        self.assertNotIn("h, 0, 0, 0", body)

    def test_minute_is_passed_to_the_template(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("data-update-minute", html)


class TestYahooCoverage(unittest.TestCase):
    """v6.2.9: a download that succeeds but returns a sliver."""

    @staticmethod
    def _frame(first, n):
        import pandas as pd
        return pd.DataFrame({"date": pd.to_datetime(pd.bdate_range(first, periods=n)),
                             "value": range(n)})

    def setUp(self):
        from datetime import date
        self.start, self.end = date(2018, 8, 15), date(2026, 8, 15)

    def test_three_weeks_of_an_eight_year_window_is_not_coverage(self):
        """The actual bug: ~15 rows passed the `len(df) < 10` guard, so no
        exception was raised and the FRED fallback never fired. The 5-year
        yield chart was a flat line with a spike at the right edge."""
        from app.data_pipeline import _covers_window
        self.assertFalse(_covers_window(self._frame("2026-07-26", 15),
                                        self.start, self.end))

    def test_full_history_passes(self):
        from app.data_pipeline import _covers_window
        self.assertTrue(_covers_window(self._frame("2018-08-15", 2000),
                                       self.start, self.end))

    def test_empty_and_none_are_not_coverage(self):
        import pandas as pd
        from app.data_pipeline import _covers_window
        self.assertFalse(_covers_window(None, self.start, self.end))
        self.assertFalse(_covers_window(pd.DataFrame(columns=["date", "value"]),
                                        self.start, self.end))

    @staticmethod
    def _futures_loop():
        """The `for comdty in futures_underlying:` loop, as an AST node.

        Located by parsing, not by slicing the source between landmarks --
        the first version of these two tests keyed on a `return {` that does
        not exist in that function, and both errored rather than testing
        anything. Comments and layout must not be able to move this.
        """
        import ast
        tree = ast.parse((ROOT / "app" / "data_pipeline.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.For)
                    and getattr(node.target, "id", "") == "comdty"
                    and getattr(node.iter, "id", "") == "futures_underlying"):
                return node
        raise AssertionError("futures download loop not found")

    def test_check_is_scoped_to_series_with_a_fallback(self):
        """A commodity contract can legitimately start part-way through the
        window, and there is nothing better to switch to -- so the coverage
        rule must only gate the two series that have a FRED equivalent."""
        import ast
        loop = self._futures_loop()
        # find the `if` whose test calls _covers_window(got, ...)
        for node in ast.walk(loop):
            if not isinstance(node, ast.If):
                continue
            calls = [n for n in ast.walk(node.test)
                     if isinstance(n, ast.Call)
                     and getattr(n.func, "id", "") == "_covers_window"
                     and getattr(n.args[0], "id", "") == "got"]
            if not calls:
                continue
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            self.assertIn("alt", names,
                          "the coverage gate must also require a fallback")
            return
        self.fail("no coverage check on the Yahoo result")

    def test_never_trades_data_for_nothing(self):
        """If FRED is also short that day, keep the short Yahoo series rather
        than replacing it with something worse."""
        import ast
        loop = self._futures_loop()
        checked_alt = [n for n in ast.walk(loop)
                       if isinstance(n, ast.Call)
                       and getattr(n.func, "id", "") == "_covers_window"
                       and getattr(n.args[0], "id", "") == "alt"]
        self.assertTrue(checked_alt,
                        "the fallback must be coverage-checked before it is used")


class TestScheduler(unittest.TestCase):
    def test_cache_age_reads_the_stamp_not_the_mtime(self):
        """Copying data/ between machines resets mtimes; the UTC stamp inside
        meta.json is the only trustworthy age."""
        src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        body = src[src.index("def _cache_age_hours"):src.index("def _start_scheduler")]
        self.assertIn("updated_at", body)
        self.assertNotIn("st_mtime", body)

    def test_missing_meta_is_treated_as_stale(self):
        sys.path.insert(0, str(ROOT))
        from app import main
        real = main.META_PATH
        try:
            main.META_PATH = ROOT / "does" / "not" / "exist.json"
            self.assertIsNone(main._cache_age_hours())
        finally:
            main.META_PATH = real

    def test_scheduler_is_not_optional(self):
        """apscheduler missing must be reported as an ERROR, not shrugged off:
        silently never updating is the worst failure this app has."""
        src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        body = src[src.index("def _start_scheduler"):src.index("def _next_run_text")]
        self.assertIn("ERROR", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
