"""Decision-oriented charts (one question per chart)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

C = {"navy": "#14213D", "teal": "#2A9D8F", "amber": "#E9A23B", "red": "#C8553D", "grey": "#8D99AE"}


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25)


def chart_capacity(avail, plan, demand, path):
    teams = sorted(avail)
    planned = [sum(p["hours"] for p in plan if p["team"] == t) for t in teams]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    x, w = list(range(len(teams))), 0.26
    ax.bar([i - w for i in x], [avail[t] for t in teams], w, label="Available hours (after buffer)", color=C["navy"])
    ax.bar(x, planned, w, label="Planned (recommended scenario)", color=C["teal"])
    ax.bar([i + w for i in x], [demand[t] for t in teams], w, label="Unconstrained demand", color=C["amber"])
    ax.set_xticks(x)
    ax.set_xticklabels(teams, rotation=15, ha="right")
    ax.set_ylabel("Selling hours / quarter")
    ax.set_title("Where does capacity bind? Demand vs. available hours by team", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def chart_scenarios(results, rec, path):
    names = list(results)
    vals = [results[n]["metrics"]["value_in_scope"] / 1e6 for n in names]
    cols = [C["teal"] if n == rec else (C["grey"] if results[n]["metrics"]["guardrails_pass"] else C["red"]) for n in names]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    bars = ax.bar(names, vals, color=cols)
    top = max(vals) if vals else 1
    for b, n, v in zip(bars, names, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + top * 0.02, f"${v:,.1f}M", ha="center", fontsize=9, fontweight="bold")
        f = results[n]["metrics"]["guardrail_failures"]
        ax.text(b.get_x() + b.get_width() / 2, top * 0.04, "Guardrails: pass" if not f else "Fails:\n" + "\n".join(f),
                ha="center", va="bottom", fontsize=7.5, color="white")
    ax.set_ylim(0, top * 1.15)
    ax.set_ylabel("Value-in-scope index (USD M)")
    ax.set_title("Scenario comparison (green = recommended, red = breaks a guardrail)", loc="left", fontweight="bold")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def chart_map(plan, path):
    fig, ax = plt.subplots(figsize=(9, 4.4))
    for tier, col in (("Not covered", C["grey"]), ("Light touch", C["amber"]), ("High touch", C["teal"])):
        pts = [p for p in plan if p["tier"] == tier]
        ax.scatter([p["score"] for p in pts], [p["value_at_stake"] / 1e3 for p in pts], s=22, alpha=0.75,
                   color=col, label=f"{tier} ({len(pts)})", edgecolor="white", linewidth=0.3)
    ax.set_yscale("log")
    ax.set_xlabel("Priority score (0-100, explainable heuristic)")
    ax.set_ylabel("Value at stake (USD K, log)")
    ax.set_title("Where the plan spends capacity: score vs. value at stake", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def chart_sensitivity(sens, path):
    rows = sorted(sens["shocks"], key=lambda r: r["value_in_scope_delta"])
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.barh([r["team"] for r in rows], [r["value_in_scope_delta"] / 1e6 for r in rows], color=C["red"])
    for i, r in enumerate(rows):
        ax.text(r["value_in_scope_delta"] / 1e6, i, f"  {r['accounts_dropped']} dropped / {r['accounts_downgraded']} downgraded",
                va="center", fontsize=8)
    ax.set_xlabel("Change in value-in-scope (USD M)")
    ax.set_title(f"What breaks first? Effect of a {rows[0]['shock_pct']:.0f}% capacity cut, one team at a time",
                 loc="left", fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.margins(x=0.35)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
