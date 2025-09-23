# Prestige Fragrance GTM — Calculator & Advisor

Brand-agnostic toolkit for prestige fragrance (LTV/payback on GM basis, promo economics, Prestige Protection Index, and guardrails). Outputs **Markdown + HTML**, and includes a **local web form** for quick previews.

## Quick start (CLI)
```bash
pip install -r requirements.txt
python core_cli.py --config sample_config.yaml --out report.md
# → generates report.md and report.html
```

## Local web form (optional)
```bash
python app.py
# then open http://127.0.0.1:5000/
```

## Config
Edit `sample_config.yaml` (price, GM%, CAC, retention, ARPU divisor, promo events, PPI inputs). Price band targets prestige 30/50 ml (~£150–£200).
