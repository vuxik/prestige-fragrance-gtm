from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import math


# ---------- Utilities ----------

def arpu_per_month(price: float, divisor: float = 12.0) -> float:
    """Conservative monthly ARPU proxy from a one-off price (e.g., 12..18 months)."""
    return price / max(1.0, divisor)

def clamp(x: float, lo: float, hi: float) -> float:
    """Clamp x to [lo, hi]."""
    return max(lo, min(hi, x))

def gm_per_order(price: float, gm_pct: float, depth: float = 0.0) -> float:
    """Gross margin per order at given discount depth (0..1)."""
    return price * (1.0 - depth) * gm_pct

def baseline_gm_over_weeks(
    baseline_weekly_units: float,
    price: float,
    gm_pct: float,
    weeks: int
) -> float:
    """GM over the horizon with no promos (baseline)."""
    return weeks * baseline_weekly_units * price * gm_pct

def promo_delta_pct(net_gm_delta: float, baseline_gm: float) -> float:
    """Return promo net GM delta as a % of baseline (can be negative)."""
    return (net_gm_delta / baseline_gm) * 100.0 if baseline_gm > 0 else 0.0

def ppi_band(ppi: float, green_max: float = 35.0, amber_max: float = 65.0) -> str:
    if ppi <= green_max:
        return "Green"
    if ppi <= amber_max:
        return "Amber"
    return "Red"


# ---------- Unit economics ----------
def ltv_gm(arpu: float, gm_pct: float, retention: float, months: int) -> float:
    gm = arpu * gm_pct
    if retention == 1.0:
        return gm * months
    return gm * (retention * (1 - retention**months) / (1 - retention))

def payback_month(arpu: float, gm_pct: float, retention: float, cac: float, months: int) -> Optional[int]:
    gm = arpu * gm_pct
    cum = 0.0
    for t in range(1, months+1):
        cum += gm * (retention ** t)
        if cum >= cac:
            return t
    return None

# ---------- Promo calendar modeling ----------

@dataclass
class PromoEvent:
    week: int          # week index (1..52 or horizon)
    depth: float       # discount fraction e.g., 0.15 for 15%
    channel: str       # 'DTC' or 'Retail' or other tag

@dataclass
class PromoEvalResult:
    net_gm_delta: float               # incremental GM vs baseline over the horizon (currency units)
    baseline_recovery_weeks: float    # simple measure of post-promo trough duration
    avg_depth: float
    promo_days_pct: float
    cannibalization_share: float
    pull_forward_share: float
    # new convenience fields (optional)
    baseline_gm: float = 0.0          # GM without promos over the same horizon
    delta_pct: float = 0.0            # net_gm_delta / baseline_gm as %

def eval_promo_calendar(
    baseline_weekly_units: float,
    list_price: float,
    gm_pct: float,
    elasticity: float,              # price elasticity magnitude (positive number, e.g., 1.2)
    weeks: int,
    events: List[PromoEvent],
    pull_forward_factor: float = 0.35,   # fraction of uplift pulled from future weeks
    cannibalization_factor: float = 0.25 # fraction of uplift that would have happened soon at full price
) -> PromoEvalResult:
    """
    Simplified model:
    - Baseline revenue = baseline_weekly_units * list_price each week
    - Promo at depth d reduces price to p=(1-d)*list_price; demand uplift ~ (1/(1-d))**elasticity
    - Gross margin per unit is gm_pct * price
    - Uplift decomposed into incremental vs pull-forward and cannibalization
    - Post-promo trough approximated proportional to pull_forward_factor and depth
    """
    baseline_gm_total = weeks * baseline_weekly_units * list_price * gm_pct

    promo_by_week = {e.week: e for e in events}
    net_gm = 0.0
    trough_penalty = 0.0

    for w in range(1, weeks + 1):
        if w in promo_by_week:
            d = clamp(promo_by_week[w].depth, 0.0, 0.8)
            price = (1 - d) * list_price
            # iso-elastic demand uplift multiplier
            mult = (1.0 / (1.0 - d)) ** max(0.0, elasticity)
            units = baseline_weekly_units * mult
            gm_week = units * price * gm_pct

            base_week_gm = baseline_weekly_units * list_price * gm_pct
            uplift = max(0.0, gm_week - base_week_gm)

            cannib = uplift * cannibalization_factor
            pull_fwd = uplift * pull_forward_factor
            incremental = uplift - cannib - pull_fwd

            # realize GM this week (baseline + decomp of uplift)
            net_gm += base_week_gm + incremental + cannib + pull_fwd
            # penalize future trough once
            trough_penalty += pull_fwd
        else:
            # non-promo week at baseline price
            net_gm += baseline_weekly_units * list_price * gm_pct

    net_gm_delta = net_gm - baseline_gm_total - trough_penalty
    avg_depth = (sum(e.depth for e in events) / len(events)) if events else 0.0
    promo_days_pct = (len(events) / weeks) if weeks > 0 else 0.0
    baseline_recovery_weeks = max(0.0, 2.0 + 10.0 * avg_depth * pull_forward_factor)

    delta_pct = promo_delta_pct(net_gm_delta, baseline_gm_total)

    return PromoEvalResult(
        net_gm_delta=net_gm_delta,
        baseline_recovery_weeks=baseline_recovery_weeks,
        avg_depth=avg_depth,
        promo_days_pct=promo_days_pct,
        cannibalization_share=cannibalization_factor,
        pull_forward_share=pull_forward_factor,
        baseline_gm=baseline_gm_total,
        delta_pct=delta_pct,
    )


# ---------- Prestige Protection Index (rescaled) ----------

def prestige_protection_index(
    promo_days_pct: float,
    avg_depth: float,
    code_share: float,
    hero_discount_incidence: float,
    leakage: float,
    weights: Dict[str, float] = None
) -> float:
    """
    PPI on 0..100.
    Accepts YAML weights as raw numbers (e.g., 22/28/18/22/10) or fractions.
    We normalize weights internally to sum to 1.0.
    Inputs are 0..1 fractions (e.g., 0.15 = 15%).
    Lower PPI = more protected prestige; higher = more risk.
    """
    # Defaults if none provided
    if weights is None:
        weights = {
            "promo_days": 0.20,
            "avg_depth":  0.25,
            "code_share": 0.25,
            "hero":       0.20,
            "leakage":    0.10,
        }

    # Normalize weights (so any numbers you pass are OK)
    total = sum(weights.values()) if weights else 0.0
    if total <= 0:
        weights = {
            "promo_days": 0.20,
            "avg_depth":  0.25,
            "code_share": 0.25,
            "hero":       0.20,
            "leakage":    0.10,
        }
        total = 1.0
    norm = {k: v / total for k, v in weights.items()}

    # Weighted sum in 0..1
    score_0_to_1 = (
        norm.get("promo_days", 0.0) * promo_days_pct +
        norm.get("avg_depth",  0.0) * avg_depth +
        norm.get("code_share", 0.0) * code_share +
        norm.get("hero",       0.0) * hero_discount_incidence +
        norm.get("leakage",    0.0) * leakage
    )

    return max(0.0, min(100.0, 100.0 * score_0_to_1))






# ---------- Influencer (stub for now) ----------
from dataclasses import dataclass
@dataclass
class Tier:
    name: str
    fee: float
    reach: float
    ctr: float
    cvr: float
    half_life_wks: float

def tier_payback_gm(
    tier: Tier, price: float, gm_pct: float, retention: float, months: int, cac_cap=None
):
    clicks = tier.reach * tier.ctr
    buyers = clicks * tier.cvr
    arpu_monthly = price / 12.0
    # Use ltv_gm for cohort *buyers*
    cohort_ltv = ltv_gm(arpu_monthly, gm_pct, retention, months) * buyers
    cac = tier.fee / max(1e-9, buyers)
    if cac_cap is not None:
        cac = min(cac, cac_cap)
    # rough payback month by comparing expected GM accumulation (not fully modeled here)
    pb = None
    cum = 0.0
    for t in range(1, months+1):
        cum += (arpu_monthly * gm_pct) * buyers * (retention ** t)
        if pb is None and cum >= tier.fee:
            pb = t
            break
    return (cohort_ltv - tier.fee, pb)

# ---------- Advisor ----------
def advisor(promo_result, ppi, price, gm_pct, retention, months, cac, code_share):
    recs = []
    from math import isfinite
    arpu_monthly = price / 12.0
    pb = payback_month(arpu_monthly, gm_pct, retention, cac, months)
    if ppi > 65:
        recs.append("Prestige risk high (PPI > 65): reduce promo frequency and depth; avoid discounting hero SKUs; substitute bundles/GWP.")
    elif ppi > 50:
        recs.append("Prestige risk moderate (PPI 50–65): tighten spacing (≥9 weeks) and cap depth at ≤20%.")
    else:
        recs.append("Prestige protected: maintain current guardrails; consider shifting one sitewide promo to a discovery-set-with-credit event.")
    if promo_result.net_gm_delta < 0:
        recs.append("Promo plan erodes net GM: cut depth or reduce event count; favor GWPs/bundles over %-off.")
    elif promo_result.net_gm_delta < price * gm_pct * 10:
        recs.append("Promo plan marginal: reallocate one promo to discovery bundle; protect hero SKUs at list.")
    else:
        recs.append("Promo calendar accretive: keep min spacing and monitor troughs.")
    if code_share > 0.4:
        recs.append("High coupon dependence: run 6–8 week detox; keep hero SKUs at list; target discounts to lapsed segments only.")
    if pb is None or pb > 12:
        recs.append("Payback >12 months: favor micro-tier creators and in-store discovery to lower CAC; avoid deep discounts to acquire.")
    else:
        recs.append("Payback within 12 months: scale channels with similar CAC.")
    if promo_result.baseline_recovery_weeks > 4:
        recs.append("Long post-promo trough: increase min spacing and add non-discount traffic drivers (sampling stands, masterclasses).")
    return recs
