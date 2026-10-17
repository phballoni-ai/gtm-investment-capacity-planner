"""Scoring, capacity-constrained allocation, scenarios and sensitivity. No randomness."""
from bisect import bisect_left, bisect_right

KEY = {"High touch": "high_touch", "Light touch": "light_touch"}


def pct_ranks(values):
    s = sorted(values)
    n = len(s)
    return [(bisect_left(s, v) + 0.5 * (bisect_right(s, v) - bisect_left(s, v))) / n * 100 for v in values]


def score_accounts(accounts, weights, bonus):
    ranks = pct_ranks([x["value_at_stake"] for x in accounts])
    out = []
    for x, rk in zip(accounts, ranks):
        comp = {"value": rk, "icp": (x["icp"] - 1) / 4 * 100, "engagement": x["engagement"] * 20,
                "strategic": 100.0 if x["strategic"] else 0.0}
        s = sum(weights[k] * comp[k] for k in comp) + bonus.get(x["relationship"], 0)
        d = dict(x)
        d["score"] = round(max(0.0, min(100.0, s)), 2)
        d["ring"] = x["late_stage_usd"] > 0
        out.append(d)
    return out


def available_hours(team, a, factor=1.0):
    return team["reps"] * team["hours_per_rep"] * (1 - a["capacity_buffer_pct"] / 100) * factor


def tier_hours(a, x, tier):
    return float(a["coverage_hours"][KEY[tier]][x["relationship"]])


def allocate(scored, teams, a, factors=None):
    """Two-pass greedy per team: ring-fenced and high-score accounts get high-touch, then light-touch."""
    factors = factors or {}
    by_team = {}
    for x in scored:
        by_team.setdefault(x["team"], []).append(x)
    plan, avail, demand = [], {}, {}
    for team in sorted(teams):
        accs = by_team.get(team, [])
        av = available_hours(teams[team], a, factors.get(team, 1.0))
        avail[team] = av
        ht_cap = av * a["max_high_touch_share"]
        order = sorted(accs, key=lambda x: (-int(x["ring"]), -x["score"], -x["value_at_stake"], x["account_id"]))
        dem = 0.0
        for x in order:
            if x["ring"] or x["score"] >= a["high_touch_min_score"]:
                dem += tier_hours(a, x, "High touch")
            elif x["score"] >= a["light_touch_min_score"]:
                dem += tier_hours(a, x, "Light touch")
        demand[team] = dem
        res, used, ht_used = {}, 0.0, 0.0
        for x in order:
            if x["ring"] or x["score"] >= a["high_touch_min_score"]:
                h = tier_hours(a, x, "High touch")
                if used + h <= av + 1e-9 and (x["ring"] or ht_used + h <= ht_cap + 1e-9):
                    res[x["account_id"]] = ("High touch", h)
                    used += h
                    ht_used += h
        for x in order:
            if x["account_id"] in res:
                continue
            if x["score"] >= a["light_touch_min_score"]:
                h = tier_hours(a, x, "Light touch")
                if used + h <= av + 1e-9:
                    res[x["account_id"]] = ("Light touch", h)
                    used += h
        for rank, x in enumerate(order, 1):
            tier, h = res.get(x["account_id"], ("Not covered", 0.0))
            hq = x["ring"] or x["score"] >= a["high_touch_min_score"]
            if tier == "High touch" and x["ring"]:
                reason = f"In-flight late-stage opportunity ring-fenced (${x['late_stage_usd']:,.0f})"
            elif tier == "High touch":
                reason = f"Score {x['score']:.0f} meets high-touch threshold; team capacity available"
            elif tier == "Light touch" and hq:
                reason = "Qualified for high-touch, but high-touch budget exhausted; light-touch fits capacity"
            elif tier == "Light touch":
                reason = f"Score {x['score']:.0f} meets light-touch threshold; fits remaining capacity"
            elif x["score"] < a["light_touch_min_score"]:
                reason = f"Score {x['score']:.0f} below coverage threshold ({a['light_touch_min_score']})"
            else:
                reason = f"Eligible (score {x['score']:.0f}) but team capacity exhausted; ranked #{rank} in team"
            d = dict(x)
            d.update({"tier": tier, "hours": h, "rank_in_team": rank, "reason": reason})
            plan.append(d)
    return plan, avail, demand


def summarize(plan, avail, demand, a):
    cap = a["value_capture"]
    cov = [p for p in plan if p["tier"] != "Not covered"]

    def vs(p):
        return p["value_at_stake"] * cap[KEY[p["tier"]]]

    vis = sum(vs(p) for p in cov)

    def share(pred):
        return sum(vs(p) for p in cov if pred(p)) / vis * 100 if vis else 0.0

    regions = sorted({p["region"] for p in plan})
    region_share = {r: share(lambda p, r=r: p["region"] == r) for r in regions}
    segments = sorted({p["segment"] for p in plan})
    segment_share = {s: share(lambda p, s=s: p["segment"] == s) for s in segments}
    strat = [p for p in plan if p["strategic"]]
    strat_cov = sum(1 for p in strat if p["tier"] != "Not covered")
    ring = [p for p in plan if p["ring"]]
    ring_val = sum(p["late_stage_usd"] for p in ring)
    ring_cov = sum(p["late_stage_usd"] for p in ring if p["tier"] != "Not covered")
    used, av = sum(p["hours"] for p in plan), sum(avail.values())
    m = {
        "accounts_total": len(plan),
        "high_touch": sum(1 for p in plan if p["tier"] == "High touch"),
        "light_touch": sum(1 for p in plan if p["tier"] == "Light touch"),
        "not_covered": sum(1 for p in plan if p["tier"] == "Not covered"),
        "hours_used": used, "hours_available": av,
        "utilization_pct": used / av * 100 if av else 0.0,
        "unconstrained_demand_hours": sum(demand.values()),
        "value_at_stake_total": sum(p["value_at_stake"] for p in plan),
        "value_at_stake_covered": sum(p["value_at_stake"] for p in cov),
        "value_in_scope": vis,
        "strategic_total": len(strat), "strategic_covered": strat_cov,
        "strategic_coverage_pct": strat_cov / len(strat) * 100 if strat else 100.0,
        "inflight_pipeline_usd": ring_val,
        "inflight_protected_pct": ring_cov / ring_val * 100 if ring_val else 100.0,
        "region_share": region_share, "segment_share": segment_share,
        "max_region": max(region_share, key=region_share.get) if region_share else "",
        "max_region_share_pct": max(region_share.values()) if region_share else 0.0,
        "customer_share_pct": share(lambda p: p["relationship"] == "customer"),
        "prospect_share_pct": share(lambda p: p["relationship"] == "prospect"),
    }
    g = a["guardrails"]
    fails = []
    if m["strategic_coverage_pct"] < g["min_strategic_coverage_pct"]:
        fails.append("Strategic coverage")
    if m["max_region_share_pct"] > g["max_single_region_share_pct"]:
        fails.append("Region concentration")
    if m["customer_share_pct"] < g["min_customer_share_pct"]:
        fails.append("Installed-base share")
    if m["prospect_share_pct"] < g["min_prospect_share_pct"]:
        fails.append("New-logo share")
    m["guardrail_failures"] = fails
    m["guardrails_pass"] = not fails
    return m


def run_scenarios(accounts, teams, a):
    results = {}
    for name, spec in a["scenarios"].items():
        scored = score_accounts(accounts, spec["weights"], spec.get("relationship_bonus", {}))
        plan, avail, demand = allocate(scored, teams, a)
        results[name] = {"spec": spec, "plan": plan, "avail": avail, "demand": demand,
                         "metrics": summarize(plan, avail, demand, a)}
    return results


def choose(results):
    ok = [n for n, r in results.items() if r["metrics"]["guardrails_pass"]]
    if ok:
        return max(ok, key=lambda n: (results[n]["metrics"]["value_in_scope"], n)), True
    n = max(results, key=lambda n: (results[n]["metrics"]["strategic_coverage_pct"],
                                    results[n]["metrics"]["value_in_scope"]))
    return n, False


def covered_ids(plan):
    return {p["account_id"] for p in plan if p["tier"] != "Not covered"}


def sensitivity(accounts, teams, a, scenario):
    spec = a["scenarios"][scenario]
    scored = score_accounts(accounts, spec["weights"], spec.get("relationship_bonus", {}))
    base_plan, base_avail, base_dem = allocate(scored, teams, a)
    base = summarize(base_plan, base_avail, base_dem, a)
    base_cov = covered_ids(base_plan)
    base_tier = {p["account_id"]: p["tier"] for p in base_plan}
    shock = a["capacity_shock_pct"]
    shocks = []
    for t in sorted(teams):
        plan, av, dm = allocate(scored, teams, a, {t: 1 - shock / 100})
        m = summarize(plan, av, dm, a)
        new_cov = covered_ids(plan)
        new_tier = {p["account_id"]: p["tier"] for p in plan}
        shocks.append({
            "team": t, "shock_pct": shock,
            "value_in_scope_delta": m["value_in_scope"] - base["value_in_scope"],
            "accounts_dropped": len(base_cov - new_cov),
            "accounts_downgraded": sum(1 for k, v in base_tier.items() if v == "High touch" and new_tier[k] == "Light touch"),
            "hours_lost": base_avail[t] - av[t],
        })
    keep, drops = set(base_cov), {}
    perturbations = 0
    for k in spec["weights"]:
        for d in (0.10, -0.10):
            w = dict(spec["weights"])
            w[k] = max(0.0, w[k] + d)
            s = sum(w.values())
            w = {kk: v / s for kk, v in w.items()}
            sc = score_accounts(accounts, w, spec.get("relationship_bonus", {}))
            plan, _, _ = allocate(sc, teams, a)
            cov = covered_ids(plan)
            perturbations += 1
            keep &= cov
            for acc in base_cov - cov:
                drops[acc] = drops.get(acc, 0) + 1
    names = {p["account_id"]: p for p in base_plan}
    marginal = sorted(({"account_id": k, "account_name": names[k]["account_name"], "team": names[k]["team"],
                        "dropped_in": v, "of": perturbations} for k, v in drops.items()),
                      key=lambda r: (-r["dropped_in"], r["account_id"]))
    return {"scenario": scenario, "shocks": shocks, "perturbations": perturbations,
            "stability_pct": len(keep) / len(base_cov) * 100 if base_cov else 100.0,
            "marginal": marginal, "base_metrics": base}
