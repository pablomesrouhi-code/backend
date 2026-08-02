"""Brand daily work log for Nabta Labo — creatives + étapes + monthly résumé."""

from __future__ import annotations

import calendar
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


def creatives_goal(cfg: dict[str, Any] | None = None) -> int:
    if not cfg:
        return DEFAULT_CREATIVES_GOAL
    try:
        g = int((cfg.get("brand_day_defaults") or {}).get("creatives_per_day", DEFAULT_CREATIVES_GOAL))
        return max(1, min(100, g))
    except (TypeError, ValueError):
        return DEFAULT_CREATIVES_GOAL


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


def month_resume(db: Session, year: int, month: int) -> dict[str, Any]:
    """Build Arabic monthly résumé vs creatives goal."""
    if month < 1 or month > 12:
        raise ValueError("invalid month")
    if year < 2020 or year > 2100:
        raise ValueError("invalid year")

    cfg = get_store_config(db)
    goal_day = creatives_goal(cfg)
    days_in_month = calendar.monthrange(year, month)[1]
    prefix = f"{year:04d}-{month:02d}-"

    today = _today_riyadh()
    # Progress window: full month, or days elapsed if current month
    if year == today.year and month == today.month:
        elapsed_days = today.day
    elif (year, month) > (today.year, today.month):
        elapsed_days = 0
    else:
        elapsed_days = days_in_month

    rows = [r for r in list_brand_days(db) if str(r.get("day") or "").startswith(prefix)]
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

    target_month = goal_day * days_in_month
    target_to_date = goal_day * max(1, elapsed_days) if elapsed_days else goal_day * days_in_month
    creatives_vs_month = round((total_creatives / target_month) * 100, 1) if target_month else 0.0
    creatives_vs_elapsed = (
        round((total_creatives / target_to_date) * 100, 1) if target_to_date else 0.0
    )
    avg_creatives = round(total_creatives / filled, 2) if filled else 0.0
    steps_pct = round((steps_done_sum / steps_possible) * 100, 1) if steps_possible else 0.0
    fill_pct = round((filled / max(1, elapsed_days)) * 100, 1) if elapsed_days else 0.0

    # Overall closeness: creatives-to-date 60% + steps 25% + fill rate 15%
    closeness = int(
        round(
            min(100, creatives_vs_elapsed) * 0.6
            + min(100, steps_pct) * 0.25
            + min(100, fill_pct) * 0.15
        )
    )

    if filled == 0:
        tone = "warn"
        label = "ما عمرتي حتى نهار"
        summary = (
            f"شهر {month:02d}/{year}: ما كاين حتى يوم مسجّل. "
            f"الهدف {goal_day} creative/يوم → {target_month} فالشهر. ابدأ عبّي النهار دابا."
        )
    elif closeness >= 90:
        tone = "ok"
        label = "فوق / على الهدف"
        summary = (
            f"خدمة قوية: {total_creatives} creative من أصل هدف حتى اليوم {target_to_date} "
            f"({creatives_vs_elapsed}%). متوسط {avg_creatives}/يوم · étapes {steps_pct}% · "
            f"أيام معبّية {filled}/{elapsed_days}."
        )
    elif closeness >= 70:
        tone = "ok"
        label = "قريب من الهدف"
        summary = (
            f"قريب: {total_creatives}/{target_to_date} creative حتى اليوم ({creatives_vs_elapsed}%). "
            f"كمّل الوتيرة {goal_day}/يوم و سدّ الثغرات فـ étapes ({steps_pct}%)."
        )
    elif closeness >= 45:
        tone = "warn"
        label = "بعيد شوية"
        gap = max(0, target_to_date - total_creatives)
        summary = (
            f"بعيد على الهدف: باقي ليك تقريباً {gap} creative باش تلحق هدف حتى اليوم. "
            f"معبّي {filled}/{elapsed_days} يوم · متوسط {avg_creatives}/يوم (الهدف {goal_day})."
        )
    else:
        tone = "bad"
        label = "بعيد بزاف على الهدف"
        gap = max(0, target_to_date - total_creatives)
        summary = (
            f"الوتيرة ضعيفة هاد الشهر: {total_creatives} creative فقط (الهدف حتى اليوم {target_to_date}). "
            f"خصّك تزيد ~{gap} creative و تعمّر الأيام الفاضية."
        )

    actions: list[str] = []
    if fill_pct < 80 and elapsed_days:
        actions.append(f"عمّر الأيام الناقصة: معبّي غير {filled} من {elapsed_days} يوم فاتو.")
    if avg_creatives < goal_day and filled:
        need = max(1, goal_day - int(avg_creatives))
        actions.append(f"زيد تقريباً +{need} creative فاليوم باش ترجع للهدف {goal_day}.")
    if steps_pct < 70 and filled:
        actions.append("الـ étapes ناقصة — خصّك تكمل الروتين كامل مش غير تنتج فيديوهات.")
    if days_hit_goal < filled and filled:
        actions.append(
            f"غير {days_hit_goal}/{filled} يوم وصلو لـ {goal_day} creative — ركّز جودة+كمّية فـ TEST."
        )
    if not actions and filled:
        actions.append("حافظ على الوتيرة، ووثّق Winner/Kill فمختبر الإعلانات كل يوم.")

    month_names_ar = [
        "",
        "يناير",
        "فبراير",
        "مارس",
        "أبريل",
        "ماي",
        "يونيو",
        "يوليوز",
        "غشت",
        "شتنبر",
        "أكتوبر",
        "نونبر",
        "دجنبر",
    ]

    return {
        "year": year,
        "month": month,
        "month_label_ar": f"{month_names_ar[month]} {year}",
        "days_in_month": days_in_month,
        "elapsed_days": elapsed_days,
        "creatives_goal_per_day": goal_day,
        "target_month": target_month,
        "target_to_date": target_to_date,
        "filled_days": filled,
        "total_creatives": total_creatives,
        "avg_creatives": avg_creatives,
        "days_hit_goal": days_hit_goal,
        "creatives_vs_month_pct": creatives_vs_month,
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


def brand_day_bootstrap(db: Session, day: str | None = None) -> dict[str, Any]:
    cfg = get_store_config(db)
    goal = creatives_goal(cfg)
    key = _day_key(day) or _today_riyadh().isoformat()
    existing = get_brand_day(db, key)
    today = _today_riyadh()
    return {
        "brand": "نبتة لابو",
        "day": key,
        "creatives_goal": goal,
        "steps_def": DAILY_STEPS,
        "entry": existing,
        "month": month_resume(db, today.year, today.month),
        "logs": list_brand_days(db)[:60],
    }
