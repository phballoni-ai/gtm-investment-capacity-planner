"""Generate the fictional demo dataset (seeded, deterministic). Deliberately includes data-quality problems."""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

AS_OF = date(2026, 10, 1)
FX = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27}
TEAMS = {  # team: (region, segment, accounts, reps)
    "NA Enterprise": ("North America", "Enterprise", 45, 4), "NA Mid-Market": ("North America", "Mid-Market", 60, 5),
    "EMEA Enterprise": ("EMEA", "Enterprise", 38, 3), "EMEA Mid-Market": ("EMEA", "Mid-Market", 52, 4),
    "APAC Mid-Market": ("APAC", "Mid-Market", 35, 2), "LATAM Mid-Market": ("LATAM", "Mid-Market", 30, 2),
}
A = ["Alder", "Brightwave", "Cobalt", "Delta", "Everline", "Fjord", "Granite", "Helix", "Ironbridge", "Juniper", "Keystone",
     "Lumen", "Northgate", "Orbit", "Pinnacle", "Quartz", "Ridgeway", "Solstice", "Tidewater", "Umbra", "Vantage",
     "Westbrook", "Xenon", "Yarrow", "Zenith"]
M = ["Freight", "Foods", "Energy", "Textiles", "Logistics", "Materials", "Components", "Pharma", "Packaging", "Machinery",
     "Marine", "Mining", "Retail", "Utilities", "Automotive", "Paper", "Steel", "Plastics", "Chemicals", "Aviation"]
S = ["Group", "Holdings", "Ltd", "GmbH", "Inc", "SA", "Partners", "Industries"]


def main(out="examples/demo"):
    rng = random.Random(2026)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    names, accounts, n = set(), [], 1000
    for team, (region, seg, count, _) in TEAMS.items():
        for _ in range(count):
            while True:
                nm = f"{rng.choice(A)} {rng.choice(M)} {rng.choice(S)}"
                if nm not in names:
                    names.add(nm)
                    break
            n += 1
            rel = "customer" if rng.random() < 0.45 else "prospect"
            median = 420000 if seg == "Enterprise" else 90000
            usd = median * rng.lognormvariate(0, 0.6)
            cur = "USD"
            if region == "EMEA":
                cur = rng.choices(["EUR", "GBP", "USD"], [65, 25, 10])[0]
            eng_w = [3, 7, 15, 25, 28, 22] if rel == "customer" else [25, 25, 22, 15, 9, 4]
            accounts.append({"account_id": f"ACC-{n}", "account_name": nm, "region": region, "segment": seg, "relationship": rel,
                             "owner_team": team, "usd": usd, "currency": cur,
                             "icp_fit": rng.choices([1, 2, 3, 4, 5], [8, 17, 30, 28, 17])[0],
                             "engagement": rng.choices([0, 1, 2, 3, 4, 5], eng_w)[0],
                             "strategic": "Y" if rng.random() < (0.14 if seg == "Enterprise" else 0.03) else "N"})
    rows = []
    for x in accounts:
        rows.append({"account_id": x["account_id"], "account_name": x["account_name"], "region": x["region"], "segment": x["segment"],
                     "relationship": x["relationship"], "owner_team": x["owner_team"],
                     "est_acv": str(round(x["usd"] / FX[x["currency"]], -2)), "currency": x["currency"],
                     "icp_fit": x["icp_fit"], "engagement": x["engagement"], "strategic": x["strategic"]})
    opps, k = [], 5000
    for x in accounts:
        if rng.random() < 0.55:
            k += 1
            stage = rng.choices(["Discovery", "Qualification", "Proposal", "Negotiation"], [30, 30, 22, 18])[0]
            amt = x["usd"] * rng.uniform(0.5, 1.2) / FX[x["currency"]]
            opps.append({"opp_id": f"OPP-{k}", "account_id": x["account_id"], "stage": stage, "amount": str(round(amt, -2)),
                         "currency": x["currency"], "close_date": (AS_OF + timedelta(days=rng.randint(10, 150))).isoformat(), "status": "open"})
    for x in rng.sample(accounts, 90):
        k += 1
        opps.append({"opp_id": f"OPP-{k}", "account_id": x["account_id"], "stage": "Closed", "amount": str(round(x["usd"] * 0.6, -2)),
                     "currency": x["currency"], "close_date": (AS_OF - timedelta(days=rng.randint(30, 400))).isoformat(),
                     "status": rng.choice(["won", "lost"])})
    # ---- seeded data-quality problems
    pool = [r for r in rows if r["strategic"] == "N"]
    for r in rng.sample(pool, 6):  # possible duplicates (new id, name variant)
        n += 1
        d = dict(r)
        d["account_id"] = f"ACC-{n}"
        d["account_name"] = r["account_name"].rsplit(" ", 1)[0] + " Inc."
        rows.append(d)
    for r in rng.sample(rows[:200], 5):
        r["est_acv"] = ""
    for r in rng.sample(rows[:200], 12):
        r["engagement"] = ""
    for r in rng.sample(rows[:200], 4):
        r["icp_fit"] = ""
    for i in range(2):  # team that has no capacity row
        n += 1
        rows.append({"account_id": f"ACC-{n}", "account_name": f"Orphan Team Industries {i}", "region": "LATAM", "segment": "Enterprise",
                     "relationship": "prospect", "owner_team": "LATAM Enterprise", "est_acv": "300000", "currency": "USD",
                     "icp_fit": 4, "engagement": 3, "strategic": "N"})
    for i in range(4):  # orphan opportunities
        k += 1
        opps.append({"opp_id": f"OPP-{k}", "account_id": f"ACC-{9001 + i}", "stage": "Proposal", "amount": "120000", "currency": "USD",
                     "close_date": (AS_OF + timedelta(days=30)).isoformat(), "status": "open"})
    open_idx = [i for i, o in enumerate(opps) if o["status"] == "open"]
    for i in rng.sample(open_idx, 8):  # stale open opportunities
        opps[i]["close_date"] = (AS_OF - timedelta(days=rng.randint(20, 120))).isoformat()
    k += 1
    opps.append({"opp_id": f"OPP-{k}", "account_id": accounts[0]["account_id"], "stage": "Proposal", "amount": "90000",
                 "currency": "BRL", "close_date": (AS_OF + timedelta(days=20)).isoformat(), "status": "open"})

    def write(name, fields, data):
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows([{k_: r.get(k_, "") for k_ in fields} for r in data])

    write("accounts.csv", ["account_id", "account_name", "region", "segment", "relationship", "owner_team", "est_acv", "currency",
                           "icp_fit", "engagement", "strategic"], rows)
    write("opportunities.csv", ["opp_id", "account_id", "stage", "amount", "currency", "close_date", "status"], opps)
    write("capacity.csv", ["team", "region", "reps", "hours_per_rep"],
          [{"team": t, "region": v[0], "reps": v[3], "hours_per_rep": 240} for t, v in TEAMS.items()])
    assumptions = {
        "_note": "All values are illustrative planning assumptions for a fictional company. Calibrate with real data before use.",
        "as_of_date": AS_OF.isoformat(), "quarter_label": "Q4 FY26", "currency": "USD", "fx_to_usd": FX,
        "coverage_hours": {"high_touch": {"customer": 45, "prospect": 70}, "light_touch": {"customer": 10, "prospect": 20}},
        "value_capture": {"high_touch": 1.0, "light_touch": 0.35},
        "capacity_buffer_pct": 15, "high_touch_min_score": 62, "light_touch_min_score": 38, "max_high_touch_share": 0.75,
        "late_stages": ["Proposal", "Negotiation"], "capacity_shock_pct": 20,
        "guardrails": {"min_strategic_coverage_pct": 80, "max_single_region_share_pct": 55,
                       "min_customer_share_pct": 30, "min_prospect_share_pct": 25},
        "scenarios": {
            "Balanced": {"description": "Even blend of value, fit, engagement and strategic importance.",
                         "weights": {"value": 0.30, "icp": 0.30, "engagement": 0.25, "strategic": 0.15}},
            "Enterprise Focus": {"description": "Concentrate on the largest accounts.",
                                 "weights": {"value": 0.55, "icp": 0.20, "engagement": 0.10, "strategic": 0.15}},
            "Install-Base Expansion": {"description": "Favor engaged existing customers.",
                                       "weights": {"value": 0.30, "icp": 0.20, "engagement": 0.35, "strategic": 0.15},
                                       "relationship_bonus": {"customer": 12}},
            "New-Logo Acquisition": {"description": "Favor high-fit prospects.",
                                     "weights": {"value": 0.35, "icp": 0.35, "engagement": 0.10, "strategic": 0.20},
                                     "relationship_bonus": {"prospect": 12}}}}
    (out / "assumptions.json").write_text(json.dumps(assumptions, indent=2), encoding="utf-8")
    print(f"Wrote demo data to {out}/ ({len(rows)} accounts, {len(opps)} opportunities)")


if __name__ == "__main__":
    main()
