"""Ads Lab — manual ad spend logs + P&L / ROAS analysis for admin dashboard."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.services.admin_economics import catalog_selling_prices_sar, cod_ops_fees_usd, sar_per_usd
from app.services.store_settings import get_store_config, save_store_config


def _f(v: Any, default: float = 0.0) -> float:
    try:
        n = float(v)
        return n if n == n else default  # NaN check
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return default


def list_ad_logs(db: Session) -> list[dict[str, Any]]:
    cfg = get_store_config(db)
    logs = cfg.get("ad_lab_logs") or []
    if not isinstance(logs, list):
        return []
    out = [x for x in logs if isinstance(x, dict)]
    out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return out


def analyze_ad_run(
    db: Session,
    *,
    spend_sar: float,
    leads: int,
    confirmed: int | None = None,
    delivered: int | None = None,
    revenue_sar: float | None = None,
    name: str = "",
    platform: str = "",
) -> dict[str, Any]:
    """Compute CPL / ROAS / net profit and Arabic verdict + tips."""

    cfg = get_store_config(db)
    pd = cfg.get("profit_defaults") or {}
    fx = max(0.01, _f(cfg.get("sar_per_usd"), sar_per_usd()))
    conf_pct = max(0.0, min(100.0, _f(pd.get("confirmation_pct"), 50.0)))
    del_pct = max(0.0, min(100.0, _f(pd.get("delivery_pct"), 70.0)))
    product_cost_usd = max(0.0, _f(pd.get("product_cost_usd"), 0.0))
    avg_pieces = max(0.0, _f(pd.get("avg_main_pieces"), 1.0))
    aov_hint = _f((cfg.get("bundle_prices_sar") or {}).get("1"), catalog_unit_price_sar())
    # Prefer realized AOV from economics if available in defaults attach — use catalog AOV estimate
    upsell = _f(cfg.get("upsell_price_sar"), 99)
    attach = max(0.0, min(1.0, _f(pd.get("upsell_attach_pct"), 0.0) / 100.0))
    aov_sar = max(0.0, avg_pieces * aov_hint + attach * upsell)

    spend = max(0.0, _f(spend_sar))
    leads_n = max(0, _i(leads))

    if confirmed is None:
        confirmed_n = int(round(leads_n * (conf_pct / 100.0)))
        confirmed_source = "estimated"
    else:
        confirmed_n = max(0, _i(confirmed))
        confirmed_source = "manual"

    if delivered is None:
        delivered_n = int(round(confirmed_n * (del_pct / 100.0)))
        delivered_source = "estimated"
    else:
        delivered_n = max(0, _i(delivered))
        delivered_source = "manual"

    returned_n = max(0, confirmed_n - delivered_n)

    if revenue_sar is None:
        revenue = round(delivered_n * aov_sar, 2)
        revenue_source = "estimated_aov"
    else:
        revenue = max(0.0, round(_f(revenue_sar), 2))
        revenue_source = "manual"

    fees = cod_ops_fees_usd()
    fee_conf = _f(fees.get("per_confirmed_lead"), 1.7)
    fee_del = _f(fees.get("per_delivered_order"), 4.0)
    fee_ret = _f(fees.get("per_return_order"), 1.3)
    fee_wh = _f(fees.get("per_fulfilled_shipment"), 0.8)

    ops_usd = (
        confirmed_n * fee_conf
        + delivered_n * fee_del
        + returned_n * fee_ret
        + delivered_n * fee_wh
    )
    ops_sar = round(ops_usd * fx, 2)
    cogs_usd = confirmed_n * avg_pieces * product_cost_usd
    cogs_sar = round(cogs_usd * fx, 2)

    ad_spend_sar = round(spend, 2)
    total_cost_sar = round(ad_spend_sar + ops_sar + cogs_sar, 2)
    profit_sar = round(revenue - total_cost_sar, 2)
    margin_pct = round((profit_sar / revenue) * 100, 1) if revenue > 0 else None
    roas = round(revenue / ad_spend_sar, 2) if ad_spend_sar > 0 else None
    cpl_sar = round(ad_spend_sar / leads_n, 2) if leads_n > 0 else None
    cpa_confirmed = round(ad_spend_sar / confirmed_n, 2) if confirmed_n > 0 else None
    cpa_delivered = round(ad_spend_sar / delivered_n, 2) if delivered_n > 0 else None

    # Max CPL for breakeven on 1 lead (same logic family as profit calculator)
    conf_r = conf_pct / 100.0
    del_r = del_pct / 100.0
    rev_per_lead = conf_r * del_r * aov_sar
    ops_per_lead_usd = (
        conf_r * fee_conf
        + conf_r * del_r * fee_del
        + conf_r * (1 - del_r) * fee_ret
        + conf_r * del_r * fee_wh
    )
    cogs_per_lead_usd = conf_r * avg_pieces * product_cost_usd
    max_cpl_sar = round(rev_per_lead - (ops_per_lead_usd + cogs_per_lead_usd) * fx, 2)

    tips: list[str] = []
    if leads_n <= 0:
        tips.append("دخل عدد الـ leads باش نقدروا نحسبو CPL.")
    if ad_spend_sar <= 0:
        tips.append("دخل صرف الإعلانات (التكلفة) باش يظهر ROAS والربح.")
    if cpl_sar is not None and max_cpl_sar > 0 and cpl_sar > max_cpl_sar:
        tips.append(
            f"CPL ديالك ({cpl_sar} ر.س) فوق حد التعادل (~{max_cpl_sar} ر.س) — خصّص الـ creative أو الـ bid."
        )
    if conf_pct < 40:
        tips.append("نسبة التأكيد ضعيفة (<40%) — حسّن سكربت الكونفيرم وجودة الـ lead قبل ما تزيد الصرف.")
    if del_pct < 60:
        tips.append("نسبة التسليم ضعيفة (<60%) — راجع المدن/العنوان والـ blacklist.")
    if roas is not None and roas < 1:
        tips.append("ROAS تحت 1 — الإعلان ما كيرجعش حتى تكلفة الإعلانات وحدها.")
    elif roas is not None and 1 <= roas < 1.5:
        tips.append("ROAS ضعيف — راك قريب من التعادل؛ ركّز على winners وزيد AOV (باقة 3 / upsell).")
    elif roas is not None and roas >= 2.5:
        tips.append("ROAS قوي — وسّع ببطء (+15–20% كل 2–3 أيام) وزيد creatives من نفس الـ angle.")
    if product_cost_usd <= 0:
        tips.append("كلفة المنتج (COGS) = 0 فالإعدادات — الربح قد يكون مبالغ فيه. عبّيها فـ «إعدادات المتجر».")
    if revenue_source == "estimated_aov":
        tips.append(
            f"الإيراد مقدَّر من AOV≈{round(aov_sar, 1)} ر.س × المسلَّم. إلا عندك رقم حقيقي دخّلو يدوياً."
        )

    if profit_sar > 0 and (roas or 0) >= 2:
        verdict = "ربح قوي"
        verdict_code = "strong_profit"
        tone = "ok"
        summary = (
            f"هاذ التشغيل رابح بقوة: ربح صافي ≈ {profit_sar} ر.س"
            + (f" · ROAS {roas}×" if roas is not None else "")
            + "."
        )
    elif profit_sar > 0:
        verdict = "رابح"
        verdict_code = "profit"
        tone = "ok"
        summary = f"رابح بصافي ≈ {profit_sar} ر.س — كمّل بحذر وحسّن CPL باش يكبر الهامش."
    elif profit_sar == 0:
        verdict = "تعادل"
        verdict_code = "breakeven"
        tone = "warn"
        summary = "على خط التعادل — أي ارتفاع فـ CPL أو انخفاض التأكيد كيحوّلك لخسارة."
    else:
        verdict = "خاسر"
        verdict_code = "loss"
        tone = "bad"
        summary = (
            f"خسارة صافية ≈ {abs(profit_sar)} ر.س. وقف التوسيع، اقتل creatives الخايبة، "
            f"وحدّ CPL تحت ~{max_cpl_sar} ر.س."
        )

    if not tips:
        tips.append("الأرقام متوازنة نسبياً — حافظ على الروتين: TEST صغير + SCALE على الـ winners.")

    return {
        "name": (name or "").strip() or "تشغيل بدون اسم",
        "platform": (platform or "").strip() or "meta",
        "inputs": {
            "spend_sar": ad_spend_sar,
            "leads": leads_n,
            "confirmed": confirmed_n,
            "delivered": delivered_n,
            "returned": returned_n,
            "revenue_sar": revenue,
            "confirmed_source": confirmed_source,
            "delivered_source": delivered_source,
            "revenue_source": revenue_source,
        },
        "assumptions": {
            "confirmation_pct": conf_pct,
            "delivery_pct": del_pct,
            "aov_sar": round(aov_sar, 2),
            "avg_main_pieces": avg_pieces,
            "product_cost_usd": product_cost_usd,
            "sar_per_usd": fx,
        },
        "metrics": {
            "cpl_sar": cpl_sar,
            "cpa_confirmed_sar": cpa_confirmed,
            "cpa_delivered_sar": cpa_delivered,
            "roas": roas,
            "max_cpl_sar": max_cpl_sar,
            "ops_sar": ops_sar,
            "cogs_sar": cogs_sar,
            "ad_spend_sar": ad_spend_sar,
            "total_cost_sar": total_cost_sar,
            "revenue_sar": revenue,
            "profit_sar": profit_sar,
            "margin_pct": margin_pct,
        },
        "verdict": {
            "code": verdict_code,
            "label_ar": verdict,
            "tone": tone,
            "summary_ar": summary,
            "tips_ar": tips[:6],
        },
    }


def save_ad_log(db: Session, entry: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    logs = list_ad_logs(db)
    row = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "name": analysis.get("name"),
        "platform": analysis.get("platform"),
        "day_start": (entry.get("day_start") or "").strip() or None,
        "day_end": (entry.get("day_end") or "").strip() or None,
        "spend_sar": analysis["inputs"]["spend_sar"],
        "leads": analysis["inputs"]["leads"],
        "confirmed": analysis["inputs"]["confirmed"],
        "delivered": analysis["inputs"]["delivered"],
        "revenue_sar": analysis["inputs"]["revenue_sar"],
        "metrics": analysis["metrics"],
        "verdict": analysis["verdict"],
        "notes": (entry.get("notes") or "").strip()[:500] or None,
    }
    logs.insert(0, row)
    # Keep last 80 runs
    logs = logs[:80]
    save_store_config(db, {"ad_lab_logs": logs})
    return row


def delete_ad_log(db: Session, log_id: str) -> bool:
    logs = list_ad_logs(db)
    nid = (log_id or "").strip()
    next_logs = [x for x in logs if str(x.get("id")) != nid]
    if len(next_logs) == len(logs):
        return False
    save_store_config(db, {"ad_lab_logs": next_logs})
    return True
