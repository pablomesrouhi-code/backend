"""Brand daily work log for Nabta Labo — creatives + étapes + monthly résumé."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.services.store_settings import get_store_config, save_store_config

STORE_TZ = ZoneInfo("Asia/Riyadh")


def _today_riyadh() -> date:
    return datetime.now(STORE_TZ).date()

# Daily goal: creatives produced for ads testing
DEFAULT_CREATIVES_GOAL = 10

# Fixed daily étapes for the brand ads workflow
DAILY_STEPS: list[dict[str, str]] = [
    {"id": "angles", "label_ar": "حضّرت زوايا / hooks جداد"},
    {"id": "produce", "label_ar": "أنتجت / عدّلت creatives"},
    {"id": "upload", "label_ar": "رفعت الإعلانات لـ Ads Manager"},
    {"id": "test", "label_ar": "شغّلت أو عدّلت TEST ads"},
    {"id": "review", "label_ar": "راجعت metrics (Winner / Kill)"},
    {"id": "scale", "label_ar": "وسّعت winners أو قررت ما نوسّعش"},
    {"id": "ops", "label_ar": "تابعت الكونفيرم / جودة الـ leads"},
]


def _i(v: Any, default: int = 0) -> int:
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return default


def _day_key(s: str | None) -> str | None:
    raw = (s or "").strip()[:10]
    if not raw:
        return None
    try:
        date.fromisoformat(raw)
        return raw
    except ValueError:
        return None


DEFAULT_PERIOD_START = "2026-08-03"
DEFAULT_PERIOD_END = "2026-09-30"


def creatives_goal(cfg: dict[str, Any] | None = None) -> int:
    if not cfg:
        return DEFAULT_CREATIVES_GOAL
    try:
        g = int((cfg.get("brand_day_defaults") or {}).get("creatives_per_day", DEFAULT_CREATIVES_GOAL))
        return max(1, min(100, g))
    except (TypeError, ValueError):
        return DEFAULT_CREATIVES_GOAL


def challenge_period(cfg: dict[str, Any] | None = None) -> tuple[date, date]:
    """Fixed challenge: from start (default today of launch) through end of September."""
    defaults = (cfg or {}).get("brand_day_defaults") or {}
    start_s = _day_key(str(defaults.get("period_start") or DEFAULT_PERIOD_START)) or DEFAULT_PERIOD_START
    end_s = _day_key(str(defaults.get("period_end") or DEFAULT_PERIOD_END)) or DEFAULT_PERIOD_END
    start = date.fromisoformat(start_s)
    end = date.fromisoformat(end_s)
    if end < start:
        start, end = end, start
    return start, end


def _inclusive_days(a: date, b: date) -> int:
    return max(0, (b - a).days + 1)


def list_brand_days(db: Session) -> list[dict[str, Any]]:
    cfg = get_store_config(db)
    rows = cfg.get("brand_day_logs") or []
    if not isinstance(rows, list):
        return []
    out = [x for x in rows if isinstance(x, dict)]
    out.sort(key=lambda x: str(x.get("day") or ""), reverse=True)
    return out


def get_brand_day(db: Session, day: str) -> dict[str, Any] | None:
    key = _day_key(day)
    if not key:
        return None
    for row in list_brand_days(db):
        if str(row.get("day")) == key:
            return row
    return None


def _normalize_steps(steps_in: Any) -> dict[str, bool]:
    src = steps_in if isinstance(steps_in, dict) else {}
    out: dict[str, bool] = {}
    for step in DAILY_STEPS:
        sid = step["id"]
        val = src.get(sid)
        out[sid] = bool(val) if val is not None else False
    return out


def _steps_done_count(steps: dict[str, bool]) -> int:
    return sum(1 for s in DAILY_STEPS if steps.get(s["id"]))


def _day_score(creatives: int, steps: dict[str, bool], goal: int) -> dict[str, Any]:
    done = _steps_done_count(steps)
    total = len(DAILY_STEPS)
    steps_pct = round((done / total) * 100) if total else 0
    creatives_pct = round(min(100, (creatives / goal) * 100)) if goal else 0
    # Weighted: creatives 55% + steps 45%
    score = int(round(creatives_pct * 0.55 + steps_pct * 0.45))
    if creatives >= goal and done >= total:
        label = "يوم كامل ✓"
        tone = "ok"
    elif creatives >= goal or done >= max(1, total - 1):
        label = "قريب من الهدف"
        tone = "warn"
    elif creatives > 0 or done > 0:
        label = "ناقص"
        tone = "warn"
    else:
        label = "فاضي"
        tone = "bad"
    return {
        "score": score,
        "steps_done": done,
        "steps_total": total,
        "steps_pct": steps_pct,
        "creatives_pct": creatives_pct,
        "label_ar": label,
        "tone": tone,
        "hit_creatives_goal": creatives >= goal,
        "hit_all_steps": done >= total,
    }


def save_brand_day(
    db: Session,
    *,
    day: str,
    creatives: int,
    steps: dict[str, bool] | None = None,
    notes: str = "",
    products: str = "",
) -> dict[str, Any]:
    key = _day_key(day)
    if not key:
        raise ValueError("invalid day")

    cfg = get_store_config(db)
    goal = creatives_goal(cfg)
    creatives_n = max(0, min(500, _i(creatives)))
    steps_n = _normalize_steps(steps or {})
    score = _day_score(creatives_n, steps_n, goal)

    logs = list_brand_days(db)
    now = datetime.now(timezone.utc).isoformat()
    existing_idx = next((i for i, r in enumerate(logs) if str(r.get("day")) == key), None)

    row = {
        "id": logs[existing_idx]["id"] if existing_idx is not None else str(uuid.uuid4()),
        "day": key,
        "creatives": creatives_n,
        "creatives_goal": goal,
        "steps": steps_n,
        "products": (products or "").strip()[:200] or None,
        "notes": (notes or "").strip()[:800] or None,
        "score": score,
        "updated_at": now,
        "created_at": (
            logs[existing_idx].get("created_at") if existing_idx is not None else now
        ),
    }

    if existing_idx is not None:
        logs[existing_idx] = row
    else:
        logs.insert(0, row)

    logs.sort(key=lambda x: str(x.get("day") or ""), reverse=True)
    logs = logs[:400]
    save_store_config(db, {"brand_day_logs": logs})
    return row


def delete_brand_day(db: Session, day_or_id: str) -> bool:
    logs = list_brand_days(db)
    key = (day_or_id or "").strip()
    next_logs = [
        x
        for x in logs
        if str(x.get("id")) != key and str(x.get("day")) != key
    ]
    if len(next_logs) == len(logs):
        return False
    save_store_config(db, {"brand_day_logs": next_logs})
    return True


def period_resume(db: Session) -> dict[str, Any]:
    """Résumé for challenge period: start → end of September vs 10 creatives/day."""
    cfg = get_store_config(db)
    goal_day = creatives_goal(cfg)
    start, end = challenge_period(cfg)
    today = _today_riyadh()

    total_days = _inclusive_days(start, end)
    if today < start:
        elapsed_days = 0
        remaining_days = total_days
    elif today > end:
        elapsed_days = total_days
        remaining_days = 0
    else:
        elapsed_days = _inclusive_days(start, today)
        remaining_days = _inclusive_days(today, end) - 1  # days after today

    start_s, end_s = start.isoformat(), end.isoformat()
    rows = [
        r
        for r in list_brand_days(db)
        if start_s <= str(r.get("day") or "") <= end_s
    ]
    rows.sort(key=lambda x: str(x.get("day") or ""))

    filled = len(rows)
    total_creatives = sum(_i(r.get("creatives")) for r in rows)
    days_hit_goal = sum(1 for r in rows if _i(r.get("creatives")) >= goal_day)
    steps_done_sum = 0
    steps_possible = 0
    for r in rows:
        st = r.get("steps") if isinstance(r.get("steps"), dict) else {}
        steps_done_sum += sum(1 for s in DAILY_STEPS if st.get(s["id"]))
        steps_possible += len(DAILY_STEPS)

    target_period = goal_day * total_days
    target_to_date = goal_day * max(1, elapsed_days) if elapsed_days else 0
    creatives_vs_period = round((total_creatives / target_period) * 100, 1) if target_period else 0.0
    creatives_vs_elapsed = (
        round((total_creatives / target_to_date) * 100, 1) if target_to_date else 0.0
    )
    avg_creatives = round(total_creatives / filled, 2) if filled else 0.0
    steps_pct = round((steps_done_sum / steps_possible) * 100, 1) if steps_possible else 0.0
    fill_pct = round((filled / max(1, elapsed_days)) * 100, 1) if elapsed_days else 0.0

    closeness = int(
        round(
            min(100, creatives_vs_elapsed) * 0.6
            + min(100, steps_pct) * 0.25
            + min(100, fill_pct) * 0.15
        )
    ) if elapsed_days else 0

    period_label = f"{start.strftime('%d/%m')} → {end.strftime('%d/%m/%Y')}"

    if filled == 0:
        tone = "warn"
        label = "ما عمرتي حتى نهار"
        summary = (
            f"الفترة {period_label}: ما كاين حتى يوم مسجّل. "
            f"الهدف {goal_day} creative/يوم × {total_days} يوم = {target_period} creative. ابدأ عبّي اليوم."
        )
    elif closeness >= 90:
        tone = "ok"
        label = "فوق / على الهدف"
        summary = (
            f"خدمة قوية على الفترة: {total_creatives}/{target_to_date} creative حتى اليوم "
            f"({creatives_vs_elapsed}%). متوسط {avg_creatives}/يوم · باقي {remaining_days} يوم حتى آخر شتنبر."
        )
    elif closeness >= 70:
        tone = "ok"
        label = "قريب من الهدف"
        summary = (
            f"قريب: {total_creatives}/{target_to_date} حتى اليوم ({creatives_vs_elapsed}%). "
            f"كمّل {goal_day}/يوم حتى {end.strftime('%d/%m')} — باقي {remaining_days} يوم."
        )
    elif closeness >= 45:
        tone = "warn"
        label = "بعيد شوية"
        gap = max(0, target_to_date - total_creatives)
        summary = (
            f"بعيد شوية على هدف الفترة: باقي ~{gap} creative باش تلحق الوتيرة حتى اليوم. "
            f"معبّي {filled}/{elapsed_days} · الهدف النهائي {target_period} قبل آخر شتنبر."
        )
    else:
        tone = "bad"
        label = "بعيد بزاف على الهدف"
        gap = max(0, target_to_date - total_creatives)
        summary = (
            f"الوتيرة ضعيفة: {total_creatives} creative فقط (المفروض حتى اليوم {target_to_date}). "
            f"خصّك ~{gap} زيادة دابا، والهدف الكامل {target_period} قبل 30/09."
        )

    actions: list[str] = []
    if fill_pct < 80 and elapsed_days:
        actions.append(f"عمّر الأيام الناقصة: {filled}/{elapsed_days} من الفترة اللي دازت.")
    if avg_creatives < goal_day and filled:
        need = max(1, goal_day - int(avg_creatives))
        actions.append(f"زيد +{need} creative/يوم باش ترجع لهدف {goal_day} حتى آخر شتنبر.")
    if steps_pct < 70 and filled:
        actions.append("الـ étapes ناقصة — كمّل الروتين كامل مش غير الفيديوهات.")
    if remaining_days and target_period:
        still_need = max(0, target_period - total_creatives)
        per_day = round(still_need / max(1, remaining_days + (0 if today > end else 1)), 1)
        actions.append(
            f"باش توصل {target_period} creative: خصّك تقريباً {per_day}/يوم فـ {remaining_days + (1 if start <= today <= end else 0)} يوم متبقّين."
        )
    if not actions and filled:
        actions.append("حافظ على الوتيرة حتى 30 شتنبر، ووثّق Winner/Kill كل يوم.")

    return {
        "period_start": start_s,
        "period_end": end_s,
        "period_label_ar": period_label,
        "month_label_ar": period_label,  # UI compat
        "total_days": total_days,
        "elapsed_days": elapsed_days,
        "remaining_days": remaining_days,
        "creatives_goal_per_day": goal_day,
        "target_month": target_period,  # UI compat
        "target_period": target_period,
        "target_to_date": target_to_date,
        "filled_days": filled,
        "total_creatives": total_creatives,
        "avg_creatives": avg_creatives,
        "days_hit_goal": days_hit_goal,
        "creatives_vs_month_pct": creatives_vs_period,
        "creatives_vs_period_pct": creatives_vs_period,
        "creatives_vs_elapsed_pct": creatives_vs_elapsed,
        "steps_pct": steps_pct,
        "fill_pct": fill_pct,
        "closeness_pct": closeness,
        "verdict": {
            "label_ar": label,
            "tone": tone,
            "summary_ar": summary,
            "actions_ar": actions[:5],
        },
        "days": [
            {
                "day": r.get("day"),
                "creatives": r.get("creatives"),
                "score": (r.get("score") or {}).get("score"),
                "label_ar": (r.get("score") or {}).get("label_ar"),
                "steps_done": (r.get("score") or {}).get("steps_done"),
                "steps_total": (r.get("score") or {}).get("steps_total"),
            }
            for r in rows
        ],
    }


def month_resume(db: Session, year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Backward-compatible alias — challenge period is the source of truth."""
    _ = year, month
    return period_resume(db)


def brand_day_bootstrap(db: Session, day: str | None = None) -> dict[str, Any]:
    cfg = get_store_config(db)
    goal = creatives_goal(cfg)
    start, end = challenge_period(cfg)
    key = _day_key(day) or _today_riyadh().isoformat()
    existing = get_brand_day(db, key)
    period = period_resume(db)
    return {
        "brand": "نبتة لابو",
        "day": key,
        "creatives_goal": goal,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "steps_def": DAILY_STEPS,
        "entry": existing,
        "month": period,
        "period": period,
        "logs": list_brand_days(db)[:60],
    }
