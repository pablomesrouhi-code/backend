"""Ads Lab — pure ad creative diagnostics (winner / kill). No COD P&L."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.services.store_settings import get_store_config, save_store_config


def _f(v: Any, default: float = 0.0) -> float:
    try:
        n = float(v)
        return n if n == n else default
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return default


def _opt_f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        n = float(v)
        if n != n:
            return None
        return n
    except (TypeError, ValueError):
        return None


def _opt_i(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return None


def _parse_day(s: str | None) -> datetime | None:
    raw = (s or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _days_span(days: int | None, day_start: str | None, day_end: str | None) -> int:
    if days is not None and days > 0:
        return max(1, int(days))
    a = _parse_day(day_start)
    b = _parse_day(day_end)
    if a and b:
        return max(1, abs((b - a).days) + 1)
    return 1


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
    spend_usd: float | None = None,
    leads: int | None = None,
    days: int | None = None,
    clicks: int | None = None,
    impressions: int | None = None,
    cpc_usd: float | None = None,
    cpm_usd: float | None = None,
    ctr_pct: float | None = None,
    hook_rate_pct: float | None = None,
    hold_rate_pct: float | None = None,
    frequency: float | None = None,
    name: str = "",
    platform: str = "",
    day_start: str | None = None,
    day_end: str | None = None,
) -> dict[str, Any]:
    """Score an ad/test on creative metrics and say: winner / test / kill."""

    days_n = _days_span(days, day_start, day_end)
    ad_spend_usd = max(0.0, round(_f(spend_usd), 2)) if spend_usd is not None else 0.0
    leads_n = max(0, _i(leads)) if leads is not None else 0
    clicks_n = _opt_i(clicks)
    imps_n = _opt_i(impressions)

    cpc_in = _opt_f(cpc_usd)
    cpm_in = _opt_f(cpm_usd)
    ctr_in = _opt_f(ctr_pct)
    hook_in = _opt_f(hook_rate_pct)
    hold_in = _opt_f(hold_rate_pct)
    freq_in = _opt_f(frequency)

    cpc = round(cpc_in, 4) if cpc_in is not None and cpc_in >= 0 else None
    if cpc is None and clicks_n and clicks_n > 0 and ad_spend_usd > 0:
        cpc = round(ad_spend_usd / clicks_n, 4)

    cpm = round(cpm_in, 4) if cpm_in is not None and cpm_in >= 0 else None
    if cpm is None and imps_n and imps_n > 0 and ad_spend_usd > 0:
        cpm = round((ad_spend_usd / imps_n) * 1000.0, 4)

    ctr = round(ctr_in, 3) if ctr_in is not None and ctr_in >= 0 else None
    if ctr is None and clicks_n is not None and imps_n and imps_n > 0:
        ctr = round((clicks_n / imps_n) * 100.0, 3)

    if clicks_n is None and cpc and cpc > 0 and ad_spend_usd > 0:
        clicks_n = int(round(ad_spend_usd / cpc))
    if imps_n is None and cpm and cpm > 0 and ad_spend_usd > 0:
        imps_n = int(round((ad_spend_usd / cpm) * 1000.0))
    if ctr is None and clicks_n and imps_n and imps_n > 0:
        ctr = round((clicks_n / imps_n) * 100.0, 3)

    hook = round(hook_in, 2) if hook_in is not None and hook_in >= 0 else None
    hold = round(hold_in, 2) if hold_in is not None and hold_in >= 0 else None
    frequency_n = round(freq_in, 2) if freq_in is not None and freq_in >= 0 else None

    cpl_usd = round(ad_spend_usd / leads_n, 2) if leads_n > 0 and ad_spend_usd > 0 else None
    daily_spend = round(ad_spend_usd / days_n, 2) if days_n else None
    daily_leads = round(leads_n / days_n, 2) if days_n and leads_n else None

    # --- Score (0–100) from available creative signals ---
    score = 50.0
    score_n = 0
    signals: list[str] = []
    actions: list[str] = []
    tips: list[str] = []

    def _add(pts: float, weight: float = 1.0) -> None:
        nonlocal score, score_n
        score += pts * weight
        score_n += weight

    if ctr is not None:
        if ctr >= 2.0:
            _add(18)
            signals.append("CTR واعر")
        elif ctr >= 1.4:
            _add(10)
            signals.append("CTR زوين")
        elif ctr >= 0.9:
            _add(0)
            signals.append("CTR متوسط")
        elif ctr >= 0.6:
            _add(-12)
            signals.append("CTR ضعيف")
        else:
            _add(-22)
            signals.append("CTR ميت")

    if hook is not None:
        # Meta hook rate (3s plays / impressions) — rough KSA UGC bands
        if hook >= 35:
            _add(16)
            signals.append("Hook قوي")
        elif hook >= 25:
            _add(8)
            signals.append("Hook مقبول")
        elif hook >= 18:
            _add(-4)
            signals.append("Hook ضعيف")
        else:
            _add(-16)
            signals.append("Hook ميت")

    if hold is not None:
        if hold >= 25:
            _add(12)
            signals.append("Hold قوي")
        elif hold >= 15:
            _add(4)
            signals.append("Hold متوسط")
        else:
            _add(-10)
            signals.append("Hold ضعيف")

    if cpc is not None:
        if cpc <= 0.15:
            _add(12)
            signals.append("CPC رخيص")
        elif cpc <= 0.28:
            _add(6)
            signals.append("CPC مقبول")
        elif cpc <= 0.45:
            _add(-6)
            signals.append("CPC غالي")
        else:
            _add(-16)
            signals.append("CPC نار")

    if cpm is not None:
        if cpm <= 7:
            _add(8)
            signals.append("CPM رخيص")
        elif cpm <= 14:
            _add(2)
            signals.append("CPM عادي")
        elif cpm <= 22:
            _add(-8)
            signals.append("CPM غالي")
        else:
            _add(-14)
            signals.append("CPM مشعل")

    if frequency_n is not None:
        if frequency_n >= 3.2:
            _add(-14)
            signals.append("تعب إعلاني")
        elif frequency_n >= 2.5:
            _add(-6)
            signals.append("Frequency عالي")
        elif frequency_n <= 1.5:
            _add(4)

    if cpl_usd is not None:
        # Soft band for Saudi COD lead gen (creative filter only — not P&L)
        if cpl_usd <= 2.5:
            _add(14)
            signals.append("CPL زوين")
        elif cpl_usd <= 4.0:
            _add(4)
            signals.append("CPL مقبول")
        elif cpl_usd <= 6.0:
            _add(-8)
            signals.append("CPL غالي")
        else:
            _add(-18)
            signals.append("CPL خاسر إعلانياً")

    final_score = int(max(0, min(100, round(score))))

    # Diagnosis combos
    if hook is not None and hook < 20 and (ctr is None or ctr < 1.0):
        actions.append(
            "الـ hook ميت: بدّل أول 1–2 ثانية بالكامل (وجه/حركة/نص صادم). هاد الإعلان ما يستاهلش SCALE."
        )
    if hook is not None and hook >= 28 and ctr is not None and ctr < 0.9:
        actions.append(
            "الناس كيوقفو لكن ما كايضغطوش — حسّن الـ CTA والنص على الشاشة فالثواني 3–8، ما تبدّلش الـ hook إلا جربتي نسخة."
        )
    if ctr is not None and ctr >= 1.5 and cpc is not None and cpc > 0.4:
        actions.append(
            "CTR زوين و CPC غالي — الـ creative كيجيب اهتمام؛ راجع placements / الجمهور الضيق، ما تقتلش الـ ad بسرعة."
        )
    if frequency_n is not None and frequency_n >= 2.8:
        actions.append(
            f"Frequency ≈ {frequency_n}: الجمهور شبع. إمّا creative جديد بنفس الـ angle، أو وسّع Broad — ما تزيدش الميزانية على نفس الفيديو."
        )
    if cpm is not None and cpm > 18 and (ctr is None or ctr < 1.2):
        actions.append(
            "CPM عالي + تفاعل ضعيف = الإعلان غالي بلا نتيجة. اقتلوا وجيب angle جديد."
        )

    # Verdict
    metrics_filled = sum(
        1
        for x in (ctr, cpc, cpm, hook, hold, frequency_n, cpl_usd)
        if x is not None
    )
    if metrics_filled < 2 and ad_spend_usd <= 0 and leads_n <= 0:
        verdict = "بيانات ناقصة"
        verdict_code = "insufficient"
        tone = "warn"
        summary = "دخل على الأقل Spend + CTR/CPC/CPM أو Hook rate باش نقدروا نحكموا على الإعلان."
        actions = ["عبّي metrics من Ads Manager (CTR · CPC · CPM · Hook rate · Frequency) وعاود حلّل."]
    elif final_score >= 72:
        verdict = "Winner — خلّيه و وسّع"
        verdict_code = "winner"
        tone = "ok"
        summary = (
            f"هاد الإعلان Winner (نقطة {final_score}/100). "
            f"خلّيه فـ SCALE، زيد الميزانية ببطء (+15–20% كل 2–3 أيام)، واصنع 2–3 variations من نفس الـ hook."
        )
        actions.insert(
            0,
            "خلّي هاد الـ ad شغال · كرّر نفس الـ angle بـ creatives جداد · ما تلمسش الـ winner باش «تحسّنو» إلا نسخة Parallel.",
        )
    elif final_score >= 55:
        verdict = "Keep testing — ما توسّعش بعد"
        verdict_code = "test"
        tone = "warn"
        summary = (
            f"متوسط (نقطة {final_score}/100) — ما تقتلوش وما تديرش SCALE كبير. "
            f"كمّل TEST بـ ${max(15, round((daily_spend or 25) * 0.8, 0))}/يوم تقريباً وجيب iterations."
        )
        actions.insert(
            0,
            "خلّيه فـ TEST فقط · بدّل نص/ـCTA أو قصّة الوسط · ما تزيدش budget حتى يطلع CTR/Hook أو ينزل CPL.",
        )
    else:
        verdict = "Kill — حيّدو"
        verdict_code = "kill"
        tone = "bad"
        summary = (
            f"ضعيف (نقطة {final_score}/100) — هاد الإعلان ما كاينفعش يكمّل يصرف. "
            "اقتلوا، خذ الدرس (hook/زاوية)، وجيب creative جديد."
        )
        actions.insert(
            0,
            "Off دابا · سجّل علاش فشل (hook؟ CTR؟ CPC؟) · ما تعاودش نفس الزاوية بحالها بلا تغيير واضح.",
        )

    # Deduplicate actions
    seen: set[str] = set()
    actions_u: list[str] = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            actions_u.append(a)
    actions_u = actions_u[:6]

    if metrics_filled < 3:
        tips.append("كل ما عبّيتي metrics أكثر (خصوصاً Hook rate + CTR + CPC) الحكم كيولي أدق.")
    if hook is None:
        tips.append("Hook rate (Video plays at 3s ÷ Impressions) مهم بزاف للفيديوهات — دخّلو من Ads Manager.")
    if ad_spend_usd > 0 and days_n >= 1 and ad_spend_usd / days_n < 10 and metrics_filled >= 2:
        tips.append("الصرف اليومي صغير — استنى شوية learning قبل ما تقتل إعلان متوسط.")
    if not tips:
        tips.append("قاعدة سريعة: Winner = خلّيه + variations · متوسط = TEST · ضعيف = Kill فوراً.")

    resume: list[str] = []
    if ad_spend_usd > 0 or days_n:
        line = f"المدّة: {days_n} يوم"
        if ad_spend_usd > 0:
            line += f" · Spend ${ad_spend_usd}"
            if daily_spend is not None:
                line += f" (~${daily_spend}/يوم)"
        resume.append(line)
    bits = []
    if ctr is not None:
        bits.append(f"CTR {ctr}%")
    if cpc is not None:
        bits.append(f"CPC ${cpc}")
    if cpm is not None:
        bits.append(f"CPM ${cpm}")
    if hook is not None:
        bits.append(f"Hook {hook}%")
    if hold is not None:
        bits.append(f"Hold {hold}%")
    if frequency_n is not None:
        bits.append(f"Freq {frequency_n}")
    if bits:
        resume.append("إعلان: " + " · ".join(bits))
    if leads_n > 0:
        resume.append(
            f"Leads: {leads_n}"
            + (f" · CPL ${cpl_usd}" if cpl_usd is not None else "")
            + (f" · ~{daily_leads}/يوم" if daily_leads is not None else "")
        )
    if signals:
        resume.append("إشارات: " + " · ".join(signals))
    resume.append(f"النقطة: {final_score}/100 → {verdict}")

    # unused db kept for API symmetry / future store defaults
    _ = db

    return {
        "name": (name or "").strip() or "إعلان بدون اسم",
        "platform": (platform or "").strip() or "meta",
        "inputs": {
            "spend_usd": ad_spend_usd,
            "leads": leads_n,
            "days": days_n,
            "clicks": clicks_n,
            "impressions": imps_n,
            "cpc_usd": cpc,
            "cpm_usd": cpm,
            "ctr_pct": ctr,
            "hook_rate_pct": hook,
            "hold_rate_pct": hold,
            "frequency": frequency_n,
            "day_start": (day_start or "").strip() or None,
            "day_end": (day_end or "").strip() or None,
        },
        "metrics": {
            "score": final_score,
            "days": days_n,
            "daily_spend_usd": daily_spend,
            "daily_leads": daily_leads,
            "spend_usd": ad_spend_usd,
            "ad_spend_usd": ad_spend_usd,
            "cpc_usd": cpc,
            "cpm_usd": cpm,
            "ctr_pct": ctr,
            "hook_rate_pct": hook,
            "hold_rate_pct": hold,
            "frequency": frequency_n,
            "clicks": clicks_n,
            "impressions": imps_n,
            "leads": leads_n,
            "cpl_usd": cpl_usd,
        },
        "verdict": {
            "code": verdict_code,
            "label_ar": verdict,
            "tone": tone,
            "summary_ar": summary,
            "resume_ar": resume,
            "actions_ar": actions_u,
            "tips_ar": tips[:4],
            "signals": signals,
        },
    }


def save_ad_log(db: Session, entry: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    logs = list_ad_logs(db)
    inp = analysis.get("inputs") or {}
    row = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "name": analysis.get("name"),
        "platform": analysis.get("platform"),
        "day_start": (entry.get("day_start") or inp.get("day_start") or "").strip() or None,
        "day_end": (entry.get("day_end") or inp.get("day_end") or "").strip() or None,
        "days": inp.get("days"),
        "spend_usd": inp.get("spend_usd"),
        "leads": inp.get("leads"),
        "clicks": inp.get("clicks"),
        "impressions": inp.get("impressions"),
        "metrics": analysis.get("metrics"),
        "verdict": analysis.get("verdict"),
        "notes": (entry.get("notes") or "").strip()[:500] or None,
    }
    logs.insert(0, row)
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
