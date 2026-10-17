import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gtm_planner.data import InputError, clean_inputs, load_assumptions, load_inputs
from gtm_planner.engine import allocate, choose, pct_ranks, run_scenarios, score_accounts, sensitivity
from gtm_planner.planner import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"


def load():
    acc, opp, cap, a = load_inputs(DEMO)
    return clean_inputs(acc, opp, cap, a), a


class DataQuality(unittest.TestCase):
    def test_seeded_issues_detected(self):
        clean, _ = load()
        rules = {i["rule"] for i in clean["issues"]}
        for r in ("Possible duplicate account", "Orphan opportunity", "Stale open opportunity", "No capacity owner",
                  "Unknown currency", "est_acv missing"):
            self.assertIn(r, rules)

    def test_duplicates_excluded_from_plan(self):
        clean, _ = load()
        dup = {i["record"] for i in clean["issues"] if i["rule"] == "Possible duplicate account"}
        self.assertTrue(dup)
        self.assertFalse(dup & {x["account_id"] for x in clean["accounts"]})

    def test_missing_column_raises(self):
        with tempfile.TemporaryDirectory() as d:
            for f in ("opportunities.csv", "capacity.csv", "assumptions.json"):
                (Path(d) / f).write_text((DEMO / f).read_text())
            (Path(d) / "accounts.csv").write_text("account_id,account_name\nA1,X\n")
            with self.assertRaises(InputError):
                load_inputs(d)

    def test_bad_weights_rejected(self):
        a = json.loads((DEMO / "assumptions.json").read_text())
        a["scenarios"]["Balanced"]["weights"]["value"] = 0.9
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.json"
            p.write_text(json.dumps(a))
            with self.assertRaises(InputError):
                load_assumptions(p)

    def test_stale_opportunity_not_counted(self):
        clean, _ = load()
        stale = [i for i in clean["issues"] if i["rule"] == "Stale open opportunity"]
        self.assertGreaterEqual(len(stale), 1)


class Engine(unittest.TestCase):
    def test_percentile_ranks(self):
        r = pct_ranks([10, 20, 30])
        self.assertLess(r[0], r[1])
        self.assertLess(r[1], r[2])

    def test_capacity_never_exceeded(self):
        clean, a = load()
        for name, res in run_scenarios(clean["accounts"], clean["teams"], a).items():
            for team, av in res["avail"].items():
                used = sum(p["hours"] for p in res["plan"] if p["team"] == team)
                self.assertLessEqual(used, av + 1e-6, f"{name}/{team}")

    def test_deterministic(self):
        clean, a = load()
        r1 = run_scenarios(clean["accounts"], clean["teams"], a)
        r2 = run_scenarios(clean["accounts"], clean["teams"], a)
        for n in r1:
            self.assertEqual([(p["account_id"], p["tier"]) for p in r1[n]["plan"]],
                             [(p["account_id"], p["tier"]) for p in r2[n]["plan"]])

    def test_scenarios_differ(self):
        clean, a = load()
        r = run_scenarios(clean["accounts"], clean["teams"], a)
        sets = {n: frozenset(p["account_id"] for p in v["plan"] if p["tier"] != "Not covered") for n, v in r.items()}
        self.assertGreater(len(set(sets.values())), 1)

    def test_capacity_shock_not_increase_value(self):
        clean, a = load()
        s = sensitivity(clean["accounts"], clean["teams"], a, "Balanced")
        for row in s["shocks"]:
            self.assertLessEqual(row["value_in_scope_delta"], 1e-6)

    def test_ring_fenced_get_high_touch_when_capacity_allows(self):
        clean, a = load()
        res = run_scenarios(clean["accounts"], clean["teams"], a)["Balanced"]
        ring = [p for p in res["plan"] if p["ring"]]
        self.assertTrue(ring)
        self.assertGreater(sum(1 for p in ring if p["tier"] == "High touch") / len(ring), 0.8)

    def test_choose_respects_guardrails(self):
        clean, a = load()
        res = run_scenarios(clean["accounts"], clean["teams"], a)
        rec, ok = choose(res)
        if ok:
            self.assertTrue(res[rec]["metrics"]["guardrails_pass"])

    def test_scoring_bounds(self):
        clean, a = load()
        for x in score_accounts(clean["accounts"], a["scenarios"]["Balanced"]["weights"], {"customer": 50}):
            self.assertTrue(0 <= x["score"] <= 100)


class EndToEnd(unittest.TestCase):
    def test_pipeline_outputs_and_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            s = run_pipeline(DEMO, Path(d) / "base")
            out = Path(d) / "base"
            for f in ("gtm_planning_model.xlsx", "gtm_investment_memo.pdf", "coverage_plan.csv", "run_summary.json",
                      "charts/capacity_vs_demand.png", "charts/scenario_comparison.png", "charts/priority_map.png", "charts/sensitivity.png"):
                self.assertTrue((out / f).stat().st_size > 1000, f)
            self.assertTrue((out / "gtm_investment_memo.pdf").read_bytes().startswith(b"%PDF"))
            from openpyxl import load_workbook
            wb = load_workbook(out / "gtm_planning_model.xlsx")
            for sh in ("Executive Summary", "Data Quality", "Assumptions", "Account Priorities", "Capacity",
                       "Scenario Comparison", "Sensitivity", "Decision Log"):
                self.assertIn(sh, wb.sheetnames)
            s2 = run_pipeline(DEMO, Path(d) / "shock", shocks=["NA Enterprise=-30"],
                              baseline=out / "coverage_plan.csv", scenario=s["recommended_scenario"])
            self.assertGreater(s2["changes_vs_baseline"]["total_changed"], 0)
            self.assertGreater(s2["changes_vs_baseline"]["lost"] + s2["changes_vs_baseline"]["downgraded"], 0)

    def test_cli_runs(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-m", "gtm_planner", "--input", str(DEMO), "--out", d],
                               cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Recommended scenario", r.stdout)

    def test_unknown_team_shock_errors(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(InputError):
                run_pipeline(DEMO, d, shocks=["Nowhere=-10"])


if __name__ == "__main__":
    unittest.main()
