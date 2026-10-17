"""Pipeline orchestration."""
import csv
import json
from pathlib import Path
from .charts import chart_capacity, chart_map, chart_scenarios, chart_sensitivity
from .data import InputError, REQUIRED, clean_inputs, load_assumptions, read_csv
from .engine import choose, run_scenarios, sensitivity
from .excel import build_workbook
from .memo import build_memo


def apply_shocks(teams, shocks):
    notes = []
    for s in shocks:
        try:
            name, pct = s.rsplit("=", 1)
            pct = float(pct)
        except ValueError:
            raise InputError(f"Invalid --capacity-shock '{s}'. Use 'Team Name=-20'")
        if name not in teams:
            raise InputError(f"Unknown team in --capacity-shock: '{name}'. Known: {', '.join(sorted(teams))}")
        teams[name]["hours_per_rep"] *= (1 + pct / 100)
        notes.append(f"{name}: {pct:+.0f}% capacity")
    return notes


def compare_baseline(plan, baseline_path, out_path):
    base = {}
    with open(baseline_path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            base[r["account_id"]] = r["tier"]
    rank = {"Not covered": 0, "Light touch": 1, "High touch": 2}
    rows = []
    for p in plan:
        old = base.get(p["account_id"], "Not in baseline")
        if old != p["tier"]:
            rows.append({"account_id": p["account_id"], "account_name": p["account_name"], "team": p["team"],
                         "previous_tier": old, "new_tier": p["tier"], "reason": p["reason"]})
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["account_id", "account_name", "team", "previous_tier", "new_tier", "reason"])
        w.writeheader()
        w.writerows(rows)
    r_ = lambda t: rank.get(t, 0)
    return {"lost": sum(1 for r in rows if r["new_tier"] == "Not covered"),
            "gained": sum(1 for r in rows if r_(r["previous_tier"]) == 0 and r_(r["new_tier"]) > 0),
            "downgraded": sum(1 for r in rows if 0 < r_(r["new_tier"]) < r_(r["previous_tier"])),
            "upgraded": sum(1 for r in rows if r_(r["previous_tier"]) > 0 and r_(r["new_tier"]) > r_(r["previous_tier"])),
            "total_changed": len(rows)}


def run_pipeline(input_dir, out_dir, assumptions_path=None, scenario=None, shocks=None, baseline=None):
    input_dir, out = Path(input_dir), Path(out_dir)
    (out / "charts").mkdir(parents=True, exist_ok=True)
    a = load_assumptions(assumptions_path or input_dir / "assumptions.json")
    acc = read_csv(input_dir / "accounts.csv", REQUIRED["accounts.csv"])
    opp = read_csv(input_dir / "opportunities.csv", REQUIRED["opportunities.csv"])
    cap = read_csv(input_dir / "capacity.csv", REQUIRED["capacity.csv"])
    clean = clean_inputs(acc, opp, cap, a)
    teams = clean["teams"]
    shock_notes = apply_shocks(teams, shocks or [])
    if not clean["accounts"]:
        raise InputError("No valid accounts after cleaning; see data quality rules in README")
    results = run_scenarios(clean["accounts"], teams, a)
    rec, ok = choose(results)
    if scenario:
        if scenario not in results:
            raise InputError(f"Unknown scenario '{scenario}'. Available: {', '.join(results)}")
        rec = scenario
    sens = sensitivity(clean["accounts"], teams, a, rec)
    plan, avail, demand = results[rec]["plan"], results[rec]["avail"], results[rec]["demand"]
    charts = {"capacity": out / "charts" / "capacity_vs_demand.png", "scenarios": out / "charts" / "scenario_comparison.png",
              "map": out / "charts" / "priority_map.png", "sensitivity": out / "charts" / "sensitivity.png"}
    chart_capacity(avail, plan, demand, charts["capacity"])
    chart_scenarios(results, rec, charts["scenarios"])
    chart_map(plan, charts["map"])
    chart_sensitivity(sens, charts["sensitivity"])
    cov_path = out / "coverage_plan.csv"
    with open(cov_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["account_id", "account_name", "owner_team", "region", "segment", "relationship", "tier", "planned_hours",
                    "priority_score", "value_at_stake_usd", "ring_fenced", "reason", "scenario"])
        for p in sorted(plan, key=lambda p: (p["team"], p["rank_in_team"])):
            w.writerow([p["account_id"], p["account_name"], p["team"], p["region"], p["segment"], p["relationship"], p["tier"],
                        p["hours"], p["score"], round(p["value_at_stake"], 2), "Y" if p["ring"] else "N", p["reason"], rec])
    changes = compare_baseline(plan, baseline, out / "plan_changes.csv") if baseline else None
    ctx = {"a": a, "clean": clean, "results": results, "rec": rec, "plan": plan, "avail": avail, "demand": demand,
           "sens": sens, "teams": teams, "charts": charts, "changes": changes}
    build_workbook(out / "gtm_planning_model.xlsx", ctx)
    build_memo(out / "gtm_investment_memo.pdf", ctx)
    summary = {"recommended_scenario": rec, "guardrails_pass": results[rec]["metrics"]["guardrails_pass"],
               "any_scenario_passes_guardrails": ok, "capacity_shocks": shock_notes,
               "data_quality": clean["stats"], "stability_pct": sens["stability_pct"],
               "scenarios": {n: {k: v for k, v in r["metrics"].items()} for n, r in results.items()}, "changes_vs_baseline": changes}
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    return summary
