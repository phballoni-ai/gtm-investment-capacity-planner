"""Input contracts, validation and reconciliation."""
import csv
import json
import re
from datetime import date
from pathlib import Path
from statistics import median


class InputError(ValueError):
    pass


REQUIRED = {
    "accounts.csv": ["account_id", "account_name", "region", "segment", "relationship", "owner_team",
                     "est_acv", "currency", "icp_fit", "engagement", "strategic"],
    "opportunities.csv": ["opp_id", "account_id", "stage", "amount", "currency", "close_date", "status"],
    "capacity.csv": ["team", "region", "reps", "hours_per_rep"],
}
LEGAL_SUFFIXES = {"inc", "ltd", "llc", "gmbh", "sa", "ag", "plc", "corp", "co", "limited"}
NEEDED_ASSUMPTIONS = ["as_of_date", "quarter_label", "fx_to_usd", "coverage_hours", "value_capture",
                      "capacity_buffer_pct", "high_touch_min_score", "light_touch_min_score",
                      "max_high_touch_share", "late_stages", "guardrails", "scenarios", "capacity_shock_pct"]


def read_csv(path, required):
    p = Path(path)
    if not p.exists():
        raise InputError(f"Missing input file: {p}")
    with p.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        cols = [c.strip() for c in (rd.fieldnames or [])]
        missing = [c for c in required if c not in cols]
        if missing:
            raise InputError(f"{p.name}: missing required columns: {', '.join(missing)}")
        rows = []
        for i, r in enumerate(rd, start=2):
            row = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            row["_line"] = i
            rows.append(row)
    return rows


def parse_num(v):
    if v is None or str(v).strip() == "":
        return None, "blank"
    try:
        x = float(str(v).replace(",", ""))
    except ValueError:
        return None, "invalid"
    if x != x or x in (float("inf"), float("-inf")):
        return None, "invalid"
    return x, "ok"


def load_assumptions(path):
    p = Path(path)
    if not p.exists():
        raise InputError(f"Missing assumptions file: {p}")
    a = json.loads(p.read_text(encoding="utf-8"))
    miss = [k for k in NEEDED_ASSUMPTIONS if k not in a]
    if miss:
        raise InputError(f"assumptions: missing keys: {', '.join(miss)}")
    for name, spec in a["scenarios"].items():
        w = spec["weights"]
        if set(w) != {"value", "icp", "engagement", "strategic"}:
            raise InputError(f"Scenario '{name}': weights must define value, icp, engagement, strategic")
        if abs(sum(w.values()) - 1) > 1e-6:
            raise InputError(f"Scenario '{name}': weights must sum to 1 (got {sum(w.values()):.3f})")
    if a["light_touch_min_score"] > a["high_touch_min_score"]:
        raise InputError("light_touch_min_score cannot exceed high_touch_min_score")
    return a


def load_inputs(folder, assumptions_path=None):
    folder = Path(folder)
    acc = read_csv(folder / "accounts.csv", REQUIRED["accounts.csv"])
    opp = read_csv(folder / "opportunities.csv", REQUIRED["opportunities.csv"])
    cap = read_csv(folder / "capacity.csv", REQUIRED["capacity.csv"])
    a = load_assumptions(assumptions_path or folder / "assumptions.json")
    return acc, opp, cap, a


def norm_key(name):
    tokens = [t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in LEGAL_SUFFIXES]
    return "".join(tokens)


def clean_inputs(accounts_raw, opps_raw, capacity_raw, a):
    """Validate, reconcile and convert to USD. Every exclusion or imputation is logged."""
    issues = []

    def issue(sev, table, rid, rule, detail, action):
        issues.append({"severity": sev, "table": table, "record": rid, "rule": rule,
                       "detail": detail, "action": action})

    fx = {k.upper(): float(v) for k, v in a["fx_to_usd"].items()}
    as_of = date.fromisoformat(a["as_of_date"])
    late = {s.lower() for s in a["late_stages"]}

    teams = {}
    for r in capacity_raw:
        if not r["team"]:
            continue
        reps, s1 = parse_num(r["reps"])
        hrs, s2 = parse_num(r["hours_per_rep"])
        if s1 != "ok" or s2 != "ok" or reps < 0 or hrs < 0:
            issue("High", "capacity", r["team"], "Invalid capacity", "reps/hours missing, non-numeric or negative",
                  "Team excluded from plan")
            continue
        if r["team"] in teams:
            issue("Medium", "capacity", r["team"], "Duplicate team row", "Later row overrides earlier one", "Used last row")
        teams[r["team"]] = {"team": r["team"], "region": r["region"], "reps": reps, "hours_per_rep": hrs}

    accounts, seen_ids, seen_keys = [], set(), {}
    all_ids = {r["account_id"] for r in accounts_raw if r["account_id"]}
    for r in accounts_raw:
        aid = r["account_id"]
        if not aid:
            issue("High", "accounts", f"line {r['_line']}", "Missing account_id", "Row has no id", "Excluded")
            continue
        if aid in seen_ids:
            issue("High", "accounts", aid, "Duplicate account_id", "Same id appears more than once",
                  "Excluded; kept first record")
            continue
        seen_ids.add(aid)
        miss = [k for k in ("account_name", "region", "segment", "relationship", "owner_team") if not r[k]]
        if miss:
            issue("High", "accounts", aid, "Missing required field", ", ".join(miss), "Excluded")
            continue
        rel = r["relationship"].lower()
        if rel not in ("prospect", "customer"):
            issue("High", "accounts", aid, "Invalid relationship", f"'{r['relationship']}'", "Excluded")
            continue
        est, st = parse_num(r["est_acv"])
        if st == "invalid" or (st == "ok" and est < 0):
            issue("High", "accounts", aid, "Invalid est_acv", f"'{r['est_acv']}'", "Excluded")
            continue
        cur = r["currency"].upper()
        if est is not None and cur not in fx:
            issue("High", "accounts", aid, "Unknown currency", f"'{r['currency']}' has no FX rate", "Excluded")
            continue
        if r["owner_team"] not in teams:
            issue("High", "accounts", aid, "No capacity owner", f"Team '{r['owner_team']}' not in capacity.csv",
                  "Excluded: cannot be planned without a team")
            continue
        key = norm_key(r["account_name"]) + "|" + r["region"].lower()
        if key in seen_keys:
            issue("High", "accounts", aid, "Possible duplicate account",
                  f"Name/region matches {seen_keys[key]}", "Excluded; kept first record")
            continue
        seen_keys[key] = aid
        icp, s_icp = parse_num(r["icp_fit"])
        if s_icp != "ok" or not 1 <= icp <= 5:
            icp = None
        eng, s_eng = parse_num(r["engagement"])
        if s_eng != "ok" or not 0 <= eng <= 5:
            eng = None
        accounts.append({
            "account_id": aid, "account_name": r["account_name"], "region": r["region"],
            "segment": r["segment"], "relationship": rel, "team": r["owner_team"],
            "strategic": r["strategic"].lower() in ("y", "yes", "true", "1"),
            "icp": icp, "engagement": eng,
            "est_acv_usd": None if est is None else est * fx[cur],
            "open_pipeline_usd": 0.0, "late_stage_usd": 0.0, "flags": [],
        })

    icp_vals = [x["icp"] for x in accounts if x["icp"] is not None]
    eng_vals = [x["engagement"] for x in accounts if x["engagement"] is not None]
    med_icp = median(icp_vals) if icp_vals else 3.0
    med_eng = median(eng_vals) if eng_vals else 2.0
    for x in accounts:
        if x["icp"] is None:
            x["icp"] = med_icp
            x["flags"].append("icp_fit imputed")
            issue("Medium", "accounts", x["account_id"], "Missing/invalid icp_fit",
                  f"Imputed with median {med_icp}", "Kept; lower confidence")
        if x["engagement"] is None:
            x["engagement"] = med_eng
            x["flags"].append("engagement imputed")
            issue("Low", "accounts", x["account_id"], "Missing/invalid engagement",
                  f"Imputed with median {med_eng}", "Kept; lower confidence")

    by_id = {x["account_id"]: x for x in accounts}
    open_valid = 0
    for r in opps_raw:
        aid = r["account_id"]
        if aid not in all_ids:
            issue("Medium", "opportunities", r["opp_id"], "Orphan opportunity",
                  f"account_id '{aid}' not found in accounts.csv", "Excluded from pipeline")
            continue
        if aid not in by_id:
            continue
        status = r["status"].lower()
        if status not in ("open", "won", "lost"):
            issue("Low", "opportunities", r["opp_id"], "Unknown status", f"'{r['status']}'", "Ignored")
            continue
        if status != "open":
            continue
        amt, st = parse_num(r["amount"])
        if st != "ok" or amt < 0:
            issue("Medium", "opportunities", r["opp_id"], "Invalid amount", f"'{r['amount']}'", "Excluded from pipeline")
            continue
        cur = r["currency"].upper()
        if cur not in fx:
            issue("Medium", "opportunities", r["opp_id"], "Unknown currency",
                  f"'{r['currency']}' has no FX rate", "Excluded from pipeline")
            continue
        try:
            cd = date.fromisoformat(r["close_date"])
        except ValueError:
            issue("Medium", "opportunities", r["opp_id"], "Invalid close_date", f"'{r['close_date']}'",
                  "Excluded from pipeline")
            continue
        if cd < as_of:
            issue("Medium", "opportunities", r["opp_id"], "Stale open opportunity",
                  f"Close date {cd} is before as-of {as_of}", "Excluded from pipeline and ring-fence; needs CRM hygiene")
            continue
        usd = amt * fx[cur]
        x = by_id[aid]
        x["open_pipeline_usd"] += usd
        if r["stage"].lower() in late:
            x["late_stage_usd"] += usd
        open_valid += 1

    final = []
    for x in accounts:
        est = x["est_acv_usd"]
        if est is None and x["open_pipeline_usd"] > 0:
            issue("Medium", "accounts", x["account_id"], "est_acv missing", "Open pipeline used as value", "Kept")
            x["flags"].append("value from pipeline")
        x["value_at_stake"] = max(est or 0.0, x["open_pipeline_usd"])
        if x["value_at_stake"] <= 0:
            issue("High", "accounts", x["account_id"], "No quantifiable value",
                  "No est_acv and no valid open pipeline", "Excluded")
            continue
        final.append(x)

    flagged = {i["record"] for i in issues if i["table"] == "accounts"}
    clean_n = sum(1 for x in final if x["account_id"] not in flagged)
    raw_n = len(accounts_raw)
    conf = clean_n / raw_n * 100 if raw_n else 0.0
    stats = {
        "accounts_raw": raw_n, "accounts_included": len(final), "accounts_excluded": raw_n - len(final),
        "accounts_clean": clean_n, "opps_raw": len(opps_raw), "open_opps_valid": open_valid,
        "issues_total": len(issues),
        "issues_high": sum(1 for i in issues if i["severity"] == "High"),
        "issues_medium": sum(1 for i in issues if i["severity"] == "Medium"),
        "issues_low": sum(1 for i in issues if i["severity"] == "Low"),
        "confidence_pct": round(conf, 1),
        "confidence_label": "High" if conf >= 90 else "Medium" if conf >= 75 else "Low",
    }
    return {"accounts": final, "teams": teams, "issues": issues, "stats": stats}
