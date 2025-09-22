#!/usr/bin/env python3
"""
Prestige Fragrance GTM — Calculator & Advisor (brand-agnostic)
- Reads a YAML config
- Computes LTV (GM-basis), CAC payback (configurable ARPU divisor)
- Evaluates promo calendar (incl. pull-forward, cannibalization)
- Computes PPI (+ band)
- Writes Markdown report AND an HTML report next to it

Usage:
  python core_cli.py --config sample_config.yaml --out report.md
  python core_cli.py --version
"""

import argparse
import os
import sys
from datetime import datetime

import yaml
import markdown as md  # HTML export

# Ensure local imports resolve
sys.path.append(os.path.dirname(__file__))

from core import (
    arpu_per_month,
    ltv_gm,
    payback_month,
    PromoEvent,
    eval_promo_calendar,
    prestige_protection_index,
    advisor,
    ppi_band,
)

VERSION = "0.3.0"
REPORT_TITLE = "Prestige Fragrance GTM — Calculator Report"
def main():
    # ---- CLI args ----
    ap = argparse.ArgumentParser(
        description="Prestige Fragrance GTM — Calculator & Advisor (brand-agnostic)"
    )
    # NOTE: --config is now optional; we enforce it only if --version is NOT used
    ap.add_argument("--config", required=False, help="YAML config path")
    ap.add_argument("--out", default="report.md", help="Output Markdown file (e.g., report.md)")
    ap.add_argument("--version", action="store_true", help="Print version and exit")
    args = ap.parse_args()

    if args.version:
        print(f"Prestige Fragrance GTM v{VERSION}")
        sys.exit(0)

    if not args.config:
        ap.error("--config is required unless --version is used")


    # ---- Load config ----
    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)

    price = float(cfg.get("price", 180))
    gm_pct = float(cfg.get("gm_pct", 0.80))
    retention = float(cfg.get("retention", 0.85))
    months = int(cfg.get("horizon_months", 24))
    cac = float(cfg.get("cac", 35))

    arpu_divisor = float(cfg.get("arpu_divisor", 18.0))
    arpu_monthly = arpu_per_month(price, arpu_divisor)

    baseline_weekly_units = float(cfg.get("baseline_weekly_units", 100))
    weeks = int(cfg.get("weeks", 26))
    elasticity = float(cfg.get("elasticity", 1.1))
    pull_fwd = float(cfg.get("pull_forward_factor", 0.35))
    cannib = float(cfg.get("cannibalization_factor", 0.25))

    events_cfg = cfg.get("promo_events", [])
    events = [PromoEvent(e["week"], e["depth"], e.get("channel", "")) for e in events_cfg]

    code_share = float(cfg.get("code_share", 0.35))
    hero_disc = float(cfg.get("hero_discount_incidence", 0.10))
    leakage = float(cfg.get("leakage", 0.08))
    weights = cfg.get("weights", None)

    # ---- Core economics ----
    ltv = ltv_gm(arpu_monthly, gm_pct, retention, months)
    pb = payback_month(arpu_monthly, gm_pct, retention, cac, months)

    # ---- Promo evaluation ----
    pe = eval_promo_calendar(
        baseline_weekly_units=baseline_weekly_units,
        list_price=price,
        gm_pct=gm_pct,
        elasticity=elasticity,
        weeks=weeks,
        events=events,
        pull_forward_factor=pull_fwd,
        cannibalization_factor=cannib,
    )

    # Baseline GM & % delta for readability
    baseline_gm = weeks * baseline_weekly_units * price * gm_pct
    delta_pct = (pe.net_gm_delta / baseline_gm) * 100.0 if baseline_gm > 0 else 0.0

    # ---- PPI ----
    ppi = prestige_protection_index(
        promo_days_pct=pe.promo_days_pct,
        avg_depth=pe.avg_depth,
        code_share=code_share,
        hero_discount_incidence=hero_disc,
        leakage=leakage,
        weights=weights,
    )
    band = ppi_band(ppi)

    # ---- Advisor ----
    recs = advisor(pe, ppi, price, gm_pct, retention, months, cac, code_share)

    # ---- Build Markdown report ----
    lines = []
    lines.append(f"# {REPORT_TITLE}\n")

    # Inputs
    lines.append("## Inputs\n")
    lines.append(
        f"- Price: £{price:.0f} (30/50 ml)\n"
        f"- GM%: {gm_pct:.0%}\n"
        f"- CAC: £{cac:.0f}\n"
        f"- Horizon: {months} months\n"
    )
    lines.append(
        f"- Baseline weekly units: {baseline_weekly_units}\n"
        f"- Weeks simulated: {weeks}\n"
        f"- Elasticity: {elasticity}\n"
    )
    if events:
        lines.append("- Promo events:\n")
        for e in events:
            lines.append(f"  - Week {e.week}: depth {e.depth:.0%} ({e.channel})\n")
    else:
        lines.append("- Promo events: none\n")

    # Core Economics
    lines.append("\n## Core Economics\n")
    lines.append(f"- LTV (GM-basis): **£{ltv:.2f}** per acquired customer\n")
    lines.append(f"- CAC payback month: **{pb if pb is not None else 'Not within horizon'}**\n")

    # Promo Evaluation
    lines.append("\n## Promo Evaluation\n")
    lines.append(
        f"- Net GM delta vs baseline (after trough): **£{pe.net_gm_delta:.2f}** "
        f"({delta_pct:+.2f}%) over {weeks} weeks\n"
    )
    lines.append(f"- Avg depth: {pe.avg_depth:.1%}; Promo weeks share: {pe.promo_days_pct:.1%}\n")
    lines.append(
        f"- Pull-forward share (assumed): {pe.pull_forward_share:.0%}; "
        f"Cannibalization share (assumed): {pe.cannibalization_share:.0%}\n"
    )
    lines.append(f"- Post-promo baseline recovery (proxy): ~{pe.baseline_recovery_weeks:.1f} weeks\n")

    # Prestige
    lines.append("\n## Prestige Protection\n")
    lines.append(f"- PPI score: **{ppi:.1f} / 100** ({band})\n")

    # Advisor
    lines.append("\n## Advisor — Recommended Actions\n")
    for r in recs:
        lines.append(f"- {r}\n")

    out_text = "\n".join(lines)

    # ---- Write Markdown ----
    with open(args.out, "w") as f:
        f.write(out_text)

    # ---- Write HTML next to the Markdown ----
    html_body = md.markdown(out_text, extensions=["tables"])
    base, _ = os.path.splitext(args.out)
    html_path = base + ".html"

    html_template = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{REPORT_TITLE}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {{
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
      margin: 32px; line-height: 1.5; color: #111;
    }}
    h1, h2, h3 {{ margin-top: 1.25em; }}
    code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    .container {{ max-width: 920px; margin: 0 auto; }}
    .toolbar {{ margin-bottom: 16px; }}
    .btn {{ background:#111; color:#fff; padding:8px 12px; border-radius:10px; text-decoration:none; }}
    .btn:hover {{ background:#333; }}
    .footer {{ margin-top: 40px; font-size: 12px; color: #666; border-top: 1px solid #eee; padding-top: 10px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="toolbar">
      <a class="btn" href="http://127.0.0.1:5000/">Open calculator</a>
    </div>
    {html_body}
    <div class="footer">
      Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}
      • Prestige Fragrance GTM v{VERSION}
    </div>
  </div>
</body>
</html>
"""

    print("DEBUG: Writing HTML to", html_path)
    with open(html_path, "w") as f:
        f.write(html_template)

    print(out_text)
    print(f"\n(Also wrote HTML → {html_path})")


if __name__ == "__main__":
    main()
