import argparse
import sys
from .data import InputError
from .planner import run_pipeline


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m gtm_planner", description="Capacity-constrained GTM planning")
    ap.add_argument("--input", default="examples/demo", help="folder with accounts.csv, opportunities.csv, capacity.csv, assumptions.json")
    ap.add_argument("--assumptions", default=None, help="override path to assumptions.json")
    ap.add_argument("--out", default="output")
    ap.add_argument("--scenario", default=None, help="force a scenario instead of the guardrail-based recommendation")
    ap.add_argument("--capacity-shock", action="append", default=[], metavar="TEAM=PCT", help="e.g. 'NA Enterprise=-20'")
    ap.add_argument("--baseline", default=None, help="previous coverage_plan.csv to compare against")
    args = ap.parse_args(argv)
    try:
        s = run_pipeline(args.input, args.out, args.assumptions, args.scenario, args.capacity_shock, args.baseline)
    except InputError as e:
        print(f"Input error: {e}", file=sys.stderr)
        return 2
    m = s["scenarios"][s["recommended_scenario"]]
    print(f"Recommended scenario: {s['recommended_scenario']} (guardrails {'PASS' if s['guardrails_pass'] else 'FAIL'})")
    print(f"High-touch {m['high_touch']} | light-touch {m['light_touch']} | not covered {m['not_covered']} | utilization {m['utilization_pct']:.0f}%")
    print(f"Data confidence: {s['data_quality']['confidence_label']} | decision stability: {s['stability_pct']:.0f}%")
    if s["changes_vs_baseline"]:
        c = s["changes_vs_baseline"]
        print(f"Vs baseline: {c['lost']} lost coverage, {c['gained']} gained, {c['downgraded']} downgraded, {c['upgraded']} upgraded")
    print(f"Outputs written to: {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
