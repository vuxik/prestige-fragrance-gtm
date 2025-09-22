#!/usr/bin/env python3
import os, sys
from flask import Flask, render_template, request, redirect, url_for
import markdown as md

# ensure we can import core.py from this folder
sys.path.append(os.path.dirname(__file__))
from core import (
    ltv_gm,
    payback_month,
    PromoEvent,
    eval_promo_calendar,
    prestige_protection_index,
    advisor,
)

app = Flask(__name__)

def _to_float(s, default=None):
    try:
        return float(s)
    except Exception:
        return default

def _parse_events(text):
    """
    Parse promo events from textarea lines like:
      6,0.15,Retail
      15,0.20,DTC
    Returns list[PromoEvent].
    """
    events = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        week = int(parts[0])
        depth = float(parts[1])
        channel = parts[2] if len(parts) >= 3 else ""
        events.append(PromoEvent(week, depth, channel))
    return events

@app.route("/", methods=["GET"])
def index():
    # sensible defaults (your current baseline)
    defaults = {
        "price": 180,
        "gm_pct": 0.80,
        "cac": 35,
        "retention": 0.85,
        "arpu_divisor": 18,
        "baseline_weekly_units": 100,
        "weeks": 26,
        "elasticity": 1.1,
        "pull_forward_factor": 0.35,
        "cannibalization_factor": 0.25,
        "code_share": 0.35,
        "hero_discount_incidence": 0.10,
        "leakage": 0.08,
        "events_text": "6,0.15,Retail\n15,0.20,DTC\n22,0.15,Retail",
    }
    return render_template("index.html", **defaults)

@app.route("/generate", methods=["POST"])
def generate():
    # read inputs
    price = _to_float(request.form.get("price"), 180)
    gm_pct = _to_float(request.form.get("gm_pct"), 0.80)
    cac = _to_float(request.form.get("cac"), 35)
    retention = _to_float(request.form.get("retention"), 0.85)
    arpu_divisor = _to_float(request.form.get("arpu_divisor"), 18)
    baseline_weekly_units = _to_float(request.form.get("baseline_weekly_units"), 100)
    weeks = int(_to_float(request.form.get("weeks"), 26))
    elasticity = _to_float(request.form.get("elasticity"), 1.1)
    pull_forward_factor = _to_float(request.form.get("pull_forward_factor"), 0.35)
    cannibalization_factor = _to_float(request.form.get("cannibalization_factor"), 0.25)
    code_share = _to_float(request.form.get("code_share"), 0.35)
    hero_discount_incidence = _to_float(request.form.get("hero_discount_incidence"), 0.10)
    leakage = _to_float(request.form.get("leakage"), 0.08)

    events = _parse_events(request.form.get("events_text"))

    # compute
    arpu_monthly = price / max(1.0, arpu_divisor)
    ltv = ltv_gm(arpu_monthly, gm_pct, retention, 24)
    pb = payback_month(arpu_monthly, gm_pct, retention, cac, 24)

    pe = eval_promo_calendar(
        baseline_weekly_units=baseline_weekly_units,
        list_price=price,
        gm_pct=gm_pct,
        elasticity=elasticity,
        weeks=weeks,
        events=events,
        pull_forward_factor=pull_forward_factor,
        cannibalization_factor=cannibalization_factor,
    )

    # baseline & pct delta
    baseline_gm = weeks * baseline_weekly_units * price * gm_pct
    delta_pct = (pe.net_gm_delta / baseline_gm) * 100.0 if baseline_gm > 0 else 0.0

    ppi = prestige_protection_index(
        promo_days_pct=pe.promo_days_pct,
        avg_depth=pe.avg_depth,
        code_share=code_share,
        hero_discount_incidence=hero_discount_incidence,
        leakage=leakage,
        weights=None,  # or pass a dict if you want
    )

    recs = advisor(pe, ppi, price, gm_pct, retention, 24, cac, code_share)

    # build markdown (reuse your CLI structure)
    md_lines = []
    md_lines.append("# Prestige Fragrance GTM — Calculator Report\n")
    md_lines.append("## Inputs\n")
    md_lines.append(f"- Price: £{price:.0f} (30/50 ml)\n- GM%: {gm_pct:.0%}\n- CAC: £{cac:.0f}\n- Horizon: 24 months\n")
    md_lines.append(f"- Baseline weekly units: {baseline_weekly_units}\n- Weeks simulated: {weeks}\n- Elasticity: {elasticity}\n")
    if events:
        md_lines.append("- Promo events:\n")
        for e in events:
            md_lines.append(f"  - Week {e.week}: depth {e.depth:.0%} ({e.channel})\n")
    else:
        md_lines.append("- Promo events: none\n")

    md_lines.append("\n## Core Economics\n")
    md_lines.append(f"- LTV (GM-basis): **£{ltv:.2f}** per acquired customer\n")
    md_lines.append(f"- CAC payback month: **{pb if pb is not None else 'Not within horizon'}**\n")

    md_lines.append("\n## Promo Evaluation\n")
    md_lines.append(
        f"- Net GM delta vs baseline (after trough): **£{pe.net_gm_delta:.2f}** "
        f"({delta_pct:+.2f}%) over {weeks} weeks\n"
    )
    md_lines.append(f"- Avg depth: {pe.avg_depth:.1%}; Promo weeks share: {pe.promo_days_pct:.1%}\n")
    md_lines.append(
        f"- Pull-forward share (assumed): {pe.pull_forward_share:.0%}; "
        f"Cannibalization share (assumed): {pe.cannibalization_share:.0%}\n"
    )
    md_lines.append(f"- Post-promo baseline recovery (proxy): ~{pe.baseline_recovery_weeks:.1f} weeks\n")

    md_lines.append("\n## Prestige Protection\n")
    md_lines.append(f"- PPI score: **{ppi:.1f} / 100**\n")

    md_lines.append("\n## Advisor — Recommended Actions\n")
    for r in recs:
        md_lines.append(f"- {r}\n")

    md_text = "".join(md_lines)
    html_report = md.markdown(md_text, extensions=["tables"])

    return render_template("report.html", html_report=html_report, md_text=md_text)

if __name__ == "__main__":
    app.run(debug=True)
