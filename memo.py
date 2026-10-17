"""Executive memo (PDF): two pages for the decision, appendix for method and data quality."""
from datetime import date
from xml.sax.saxutils import escape
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY, TEAL = colors.HexColor("#14213D"), colors.HexColor("#2A9D8F")


def money(x):
    return f"${x / 1e6:,.1f}M" if abs(x) >= 1e6 else f"${x / 1e3:,.0f}K"


def _img(path, width):
    with PILImage.open(path) as im:
        w, h = im.size
    return Image(str(path), width=width, height=width * h / w)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.grey)
    canvas.drawString(0.7 * inch, 0.45 * inch, "Demo data is fictional. Planning model, not a revenue forecast. Human approval required.")
    canvas.drawRightString(7.8 * inch, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build_memo(path, ctx):
    a, clean, results, rec = ctx["a"], ctx["clean"], ctx["results"], ctx["rec"]
    plan, sens, charts, changes = ctx["plan"], ctx["sens"], ctx["charts"], ctx.get("changes")
    m = results[rec]["metrics"]
    ss = getSampleStyleSheet()
    H = ParagraphStyle("H", parent=ss["Heading2"], textColor=NAVY, spaceBefore=8, spaceAfter=4, fontSize=12)
    T = ParagraphStyle("T", parent=ss["Title"], textColor=NAVY, fontSize=18, alignment=0, spaceAfter=2)
    B = ParagraphStyle("B", parent=ss["BodyText"], fontSize=9.2, leading=12.2)
    S = ParagraphStyle("S", parent=B, fontSize=8, textColor=colors.grey)
    BL = ParagraphStyle("BL", parent=B, leftIndent=10, bulletIndent=0)
    cell = ParagraphStyle("c", parent=B, fontSize=8, leading=10)

    def bullets(items):
        return [Paragraph(i, BL, bulletText="\u2022") for i in items]

    big = max(sens["shocks"], key=lambda r: -r["value_in_scope_delta"])
    left = sorted((p for p in plan if p["tier"] == "Not covered" and p["score"] >= a["light_touch_min_score"]),
                  key=lambda p: -p["value_at_stake"])[:6]
    f = []
    f.append(Paragraph(f"Quarterly GTM Investment Memo: {escape(a['quarter_label'])}", T))
    f.append(Paragraph("For: CRO, CFO, CMO &nbsp;|&nbsp; Company: fictional demo (Meridian Field Systems) &nbsp;|&nbsp; "
                       f"Status: proposed for approval &nbsp;|&nbsp; Data as of {a['as_of_date']}", S))
    f.append(Paragraph("Decision requested", H))
    f.append(Paragraph(
        f"Approve the <b>{escape(rec)}</b> coverage plan: use {m['hours_used']:,.0f} of {m['hours_available']:,.0f} available selling hours "
        f"({m['utilization_pct']:.0f}%) on <b>{m['high_touch']} high-touch</b> and <b>{m['light_touch']} light-touch</b> accounts. "
        f"{m['not_covered']} accounts are deliberately not covered this quarter, including "
        f"{sum(1 for p in plan if p['tier']=='Not covered' and p['score']>=a['light_touch_min_score'])} that meet the score threshold but exceed capacity.", B))
    kpi = [["Value at stake covered", "Value-in-scope index", "Strategic accounts covered", "In-flight late-stage pipeline protected", "Data confidence"],
           [money(m["value_at_stake_covered"]), money(m["value_in_scope"]),
            f"{m['strategic_covered']}/{m['strategic_total']} ({m['strategic_coverage_pct']:.0f}%)",
            f"{m['inflight_protected_pct']:.0f}% of {money(m['inflight_pipeline_usd'])}",
            f"{clean['stats']['confidence_label']} ({clean['stats']['confidence_pct']:.0f}%)"]]
    t = Table([[Paragraph(x, cell) for x in kpi[0]], [Paragraph(f"<b>{escape(x)}</b>", cell) for x in kpi[1]]], colWidths=[1.4 * inch] * 5)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F4")), ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    f += [Spacer(1, 4), t, Paragraph("Why this scenario", H)]
    rows = [["Scenario", "Value-in-scope", "Strategic cov.", "Installed base", "New logo", "Top region", "Guardrails"]]
    for n, r in results.items():
        x = r["metrics"]
        rows.append([n + (" (rec.)" if n == rec else ""), money(x["value_in_scope"]), f"{x['strategic_coverage_pct']:.0f}%",
                     f"{x['customer_share_pct']:.0f}%", f"{x['prospect_share_pct']:.0f}%",
                     f"{x['max_region']} {x['max_region_share_pct']:.0f}%",
                     "Pass" if x["guardrails_pass"] else "Fail: " + ", ".join(x["guardrail_failures"])])
    t2 = Table([[Paragraph(str(c), cell) for c in r] for r in rows], colWidths=[x * inch for x in (1.25, 0.8, 0.75, 0.75, 0.65, 1.0, 1.9)])
    t2.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F4")), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    f += [t2, Spacer(1, 4), Paragraph(
        "The top raw-value scenario fails the strategic-coverage guardrail by roughly one account. "
        "Confirm that threshold with leadership before approving a lower-value plan.", B), Spacer(1, 4), Paragraph(
        "Selection rule: highest value-in-scope among scenarios that satisfy every guardrail "
        f"(strategic coverage >= {a['guardrails']['min_strategic_coverage_pct']}%, one region <= {a['guardrails']['max_single_region_share_pct']}% of value, "
        f"installed base >= {a['guardrails']['min_customer_share_pct']}%, new logo >= {a['guardrails']['min_prospect_share_pct']}%). "
        "Guardrails are illustrative and must be set by leadership.", S), Spacer(1, 4), _img(charts["scenarios"], 6.3 * inch), PageBreak()]

    f.append(Paragraph("Where capacity binds and what we are not doing", H))
    f.append(_img(charts["capacity"], 6.0 * inch))
    if left:
        lt = [["Not covered (highest value)", "Team", "Value at stake", "Reason"]]
        for p in left:
            lt.append([p["account_name"], p["team"], money(p["value_at_stake"]), p["reason"]])
        t3 = Table([[Paragraph(escape(str(c)), cell) for c in r] for r in lt], colWidths=[1.7 * inch, 1.2 * inch, 0.9 * inch, 3.3 * inch])
        t3.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F4")), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                                ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        f += [Spacer(1, 4), t3]
    f.append(Paragraph("What would change this recommendation", H))
    items = [f"Most exposed team: a {a['capacity_shock_pct']}% capacity cut in <b>{escape(big['team'])}</b> drops {big['accounts_dropped']} accounts "
             f"and changes value-in-scope by {money(big['value_in_scope_delta'])}.",
             f"Decision stability: <b>{sens['stability_pct']:.0f}%</b> of covered accounts stay covered across {sens['perturbations']} weight perturbations; "
             f"{len(sens['marginal'])} accounts are marginal and need manager judgment."]
    if changes:
        items.append(f"Versus the baseline plan: {changes['lost']} accounts lost coverage, {changes['gained']} gained, "
                     f"{changes['downgraded']} downgraded, {changes['upgraded']} upgraded.")
    f += bullets(items)
    f.append(Paragraph("Approvals and validation required", H))
    f += bullets(["<b>Sales:</b> confirm rep capacity, hours per coverage tier and the ring-fenced in-flight deals.",
                  "<b>Marketing:</b> provide air cover (campaigns, content) for light-touch accounts that receive no dedicated rep time.",
                  "<b>Finance:</b> validate value capture factors and guardrails against the last four quarters before using any figure externally.",
                  f"<b>RevOps:</b> resolve {clean['stats']['issues_high']} high-severity data issues; {clean['stats']['accounts_excluded']} accounts were excluded from this plan."])
    f.append(PageBreak())
    f.append(Paragraph("Appendix: method, definitions and limits", H))
    f += bullets([
        "<b>Value at stake</b> = max(estimated ACV, valid open pipeline), converted to USD. Avoids double counting an opportunity and its account estimate.",
        "<b>Priority score (0-100)</b> = weighted value percentile, ICP fit, engagement, strategic flag (+ optional relationship bonus). Weights are visible per scenario. It is an explainable heuristic, <b>not</b> a win probability.",
        "<b>Allocation</b>: per team, ring-fenced late-stage accounts and accounts above the high-touch threshold get high-touch first, then remaining capacity goes to light-touch by score.",
        "<b>Value-in-scope index</b> = value at stake x capture factor of the assigned tier. A planning index for comparing scenarios, <b>not</b> a revenue forecast or guaranteed ROI.",
        "<b>Sensitivity</b>: one team's capacity is cut at a time; each scenario weight is moved +/-10 points and renormalized.",
        "<b>Limits</b>: no historical win rates are used. Hours per tier and capture factors are assumptions to calibrate with real data. Final decisions stay with leadership."])
    s = clean["stats"]
    f.append(Paragraph("Data quality summary", H))
    f.append(Paragraph(f"{s['accounts_raw']} accounts received, {s['accounts_included']} planned, {s['accounts_excluded']} excluded. "
                       f"Issues: {s['issues_high']} high, {s['issues_medium']} medium, {s['issues_low']} low. "
                       f"Data confidence: {s['confidence_label']} ({s['confidence_pct']}% of received accounts had no issue). Full log in the Excel model.", B))
    top = {}
    for i in clean["issues"]:
        top[i["rule"]] = top.get(i["rule"], 0) + 1
    f += bullets([f"{escape(k)}: {v}" for k, v in sorted(top.items(), key=lambda kv: -kv[1])[:8]])
    f.append(Spacer(1, 6))
    f.append(_img(charts["map"], 5.6 * inch))
    SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                      topMargin=0.6 * inch, bottomMargin=0.7 * inch,
                      title=f"GTM Investment Memo {a['quarter_label']}", author="GTM Allocation Engine").build(
        f, onFirstPage=_footer, onLaterPages=_footer)
