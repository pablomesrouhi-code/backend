"""Telegram push when a new store order (or marketing lead row) is saved."""

from __future__ import annotations

import logging
import os
from typing import Literal

import httpx

from app.services.catalog import resolve_product

logger = logging.getLogger(__name__)

Outcome = Literal["ok", "skipped", "failed"]


def _truthy_env(name: str, default: str = "true") -> bool:
    raw = os.getenv(name, default).strip().lower()
    return raw not in ("0", "false", "no", "off")


def _telegram_credentials() -> tuple[str, str] | None:
    if not _truthy_env("TELEGRAM_NOTIFY_ENABLED", "true"):
        return None
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return token, chat_id


def _short_product_label(product_id: str) -> str:
    ar, _en = resolve_product(product_id)
    short = ar.split(" - ")[0].strip()
    return short or ar[:48]


def _format_lines(lines: list[tuple[str, int]]) -> str:
    parts: list[str] = []
    for pid, qty in lines:
        parts.append(f"{_short_product_label(pid)} ×{qty}")
    return " · ".join(parts) if parts else "—"


def format_order_telegram_message(
    *,
    order_number: str,
    customer_name: str,
    phone_local: str,
    total_sar: int,
    lines: list[tuple[str, int]],
    accepted_upsell: bool,
) -> str:
    products = _format_lines(lines)
    upsell = "نعم" if accepted_upsell else "لا"
    return (
        "🛒 <b>طلب جديد — نبتة لابو</b>\n\n"
        f"<b>{order_number}</b>\n"
        f"👤 {customer_name}\n"
        f"📞 <code>{phone_local}</code>\n"
        f"📦 {products}\n"
        f"💰 <b>{total_sar} ر.س</b> · دفع عند الاستلام\n"
        f"➕ Upsell: {upsell}"
    )


def format_marketing_lead_telegram_message(
    *,
    sheet_order_id: str,
    customer_name: str,
    phone_local: str,
    total_sar: float,
    lines: list[tuple[str, int]],
) -> str:
    products = _format_lines(lines)
    total = int(round(total_sar))
    return (
        "📣 <b>Lead (Meta) — نبتة لابو</b>\n\n"
        f"<b>{sheet_order_id}</b>\n"
        f"👤 {customer_name}\n"
        f"📞 <code>{phone_local}</code>\n"
        f"📦 {products}\n"
        f"💰 ~{total} ر.س"
    )


def format_checkout_capture_telegram_message(
    *,
    sheet_order_id: str,
    customer_name: str,
    phone_local: str,
    total_sar: float,
    lines: list[tuple[str, int]],
    failure_status: int | None,
    sheet_outcome: str,
) -> str:
    products = _format_lines(lines)
    total = int(round(total_sar))
    status = f"HTTP {failure_status}" if failure_status else "خطأ"
    return (
        "⚠️ <b>Checkout فاشل — نبتة لابو</b>\n\n"
        f"<b>{sheet_order_id}</b>\n"
        f"👤 {customer_name}\n"
        f"📞 <code>{phone_local}</code>\n"
        f"📦 {products}\n"
        f"💰 ~{total} ر.س\n"
        f"❗ {status} · Sheet: {sheet_outcome}"
    )


def send_telegram_html(text: str) -> tuple[Outcome, str | None]:
    creds = _telegram_credentials()
    if creds is None:
        return "skipped", "telegram_not_configured"

    token, chat_id = creds
    silent = not _truthy_env("TELEGRAM_SOUND_ENABLED", "true")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_notification": silent,
    }

    try:
        with httpx.Client(timeout=12.0) as client:
            resp = client.post(url, json=payload)
    except httpx.HTTPError as e:
        logger.warning("[telegram] send failed: %s", e)
        return "failed", str(e)[:500]

    if resp.status_code != 200:
        body = resp.text[:400]
        logger.warning("[telegram] HTTP %s: %s", resp.status_code, body)
        return "failed", f"http_{resp.status_code}: {body}"

    try:
        data = resp.json()
    except ValueError:
        return "failed", "invalid_json_response"

    if not data.get("ok"):
        desc = str(data.get("description") or "telegram_api_error")
        logger.warning("[telegram] api error: %s", desc)
        return "failed", desc[:500]

    return "ok", None


def notify_new_order(
    *,
    order_number: str,
    customer_name: str,
    phone_local: str,
    total_sar: int,
    lines: list[tuple[str, int]],
    accepted_upsell: bool,
) -> tuple[Outcome, str | None]:
    text = format_order_telegram_message(
        order_number=order_number,
        customer_name=customer_name.strip(),
        phone_local=phone_local,
        total_sar=total_sar,
        lines=lines,
        accepted_upsell=accepted_upsell,
    )
    outcome, err = send_telegram_html(text)
    logger.info(
        "[telegram] order_notify order_number=%s outcome=%s detail=%s",
        order_number,
        outcome,
        (err[:120] if err else None),
    )
    return outcome, err


def notify_marketing_lead(
    *,
    sheet_order_id: str,
    customer_name: str,
    phone_local: str,
    total_sar: float,
    lines: list[tuple[str, int]],
) -> tuple[Outcome, str | None]:
    if not _truthy_env("TELEGRAM_NOTIFY_MARKETING_LEADS", "true"):
        return "skipped", "marketing_leads_disabled"

    text = format_marketing_lead_telegram_message(
        sheet_order_id=sheet_order_id,
        customer_name=customer_name,
        phone_local=phone_local,
        total_sar=total_sar,
        lines=lines,
    )
    outcome, err = send_telegram_html(text)
    logger.info(
        "[telegram] marketing_lead_notify order_id=%s outcome=%s",
        sheet_order_id,
        outcome,
    )
    return outcome, err


def notify_checkout_capture(
    *,
    sheet_order_id: str,
    customer_name: str,
    phone_local: str,
    total_sar: float,
    lines: list[tuple[str, int]],
    failure_status: int | None,
    sheet_outcome: str,
) -> tuple[Outcome, str | None]:
    if not _truthy_env("TELEGRAM_NOTIFY_CHECKOUT_CAPTURES", "true"):
        return "skipped", "checkout_captures_disabled"

    text = format_checkout_capture_telegram_message(
        sheet_order_id=sheet_order_id,
        customer_name=customer_name,
        phone_local=phone_local,
        total_sar=total_sar,
        lines=lines,
        failure_status=failure_status,
        sheet_outcome=sheet_outcome,
    )
    outcome, err = send_telegram_html(text)
    logger.info(
        "[telegram] checkout_capture_notify order_id=%s outcome=%s",
        sheet_order_id,
        outcome,
    )
    return outcome, err
