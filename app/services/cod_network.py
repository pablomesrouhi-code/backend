"""Push confirmed store orders to COD Network seller leads API."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal, get_engine
from app.models.order_models import Order
from app.services.catalog import resolve_product
from app.services.sheet_webhook import sheet_order_public_id

logger = logging.getLogger(__name__)


def cod_network_enabled() -> bool:
    flag = (os.getenv("COD_NETWORK_ENABLED") or "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return bool(_api_token())


def _api_token() -> str:
    return (os.getenv("COD_NETWORK_API_TOKEN") or os.getenv("COD_NETWORK_BEARER_TOKEN") or "").strip()


def _api_base() -> str:
    return (
        os.getenv("COD_NETWORK_API_BASE", "https://api.cod.network/api/v2/seller") or ""
    ).strip().rstrip("/")


def _sku_map() -> dict[str, str]:
    """``COD_NETWORK_SKU_MAP=rawnaq-c:SLOFHA,laylmag:SLOFHA`` (product_id → COD SKU)."""

    out: dict[str, str] = {}
    raw = (os.getenv("COD_NETWORK_SKU_MAP") or "").strip()
    if raw:
        for part in raw.split(","):
            piece = part.strip()
            if not piece or ":" not in piece:
                continue
            pid, sku = piece.split(":", 1)
            pid = pid.strip().lower()
            sku = sku.strip()
            if pid and sku:
                out[pid] = sku
    default = (os.getenv("COD_NETWORK_DEFAULT_SKU") or "").strip()
    if default and "*" not in out:
        out.setdefault("*", default)
    return out


def resolve_cod_sku(product_id: str) -> str:
    key = product_id.strip().lower()
    mapping = _sku_map()
    if key in mapping:
        return mapping[key]
    if "*" in mapping:
        return mapping["*"]
    default = (os.getenv("COD_NETWORK_DEFAULT_SKU") or "").strip()
    if default:
        return default
    raise ValueError(f"No COD Network SKU for product_id={product_id}")


def _phone_e164(phone_e164: str, phone_digits: str) -> str:
    e = (phone_e164 or "").strip()
    if e.startswith("+"):
        return e
    d = "".join(ch for ch in (phone_digits or "") if ch.isdigit())
    if d.startswith("966"):
        return f"+{d}"
    if d.startswith("05") and len(d) >= 10:
        return f"+966{d[1:]}"
    if d:
        return f"+{d}" if not d.startswith("+") else d
    raise ValueError("missing phone")


def build_cod_network_lead_payload(
    *,
    customer_name: str,
    phone_e164: str,
    phone_digits: str,
    order_number: str,
    lines: list[tuple[str, int]],
    source_page: str | None = None,
    total_sar: float | None = None,
) -> dict[str, Any]:
    """Build JSON body for ``POST {base}/leads``."""

    qty_by_sku: dict[str, int] = {}
    for product_id, qty in lines:
        resolve_product(product_id)
        sku = resolve_cod_sku(product_id)
        qty_by_sku[sku] = qty_by_sku.get(sku, 0) + int(qty)

    items = [{"sku": sku, "quantity": q} for sku, q in sorted(qty_by_sku.items())]
    if not items:
        raise ValueError("empty items for COD Network lead")

    payload: dict[str, Any] = {
        "phone": _phone_e164(phone_e164, phone_digits),
        "customer_name": customer_name.strip(),
        "order-id": sheet_order_public_id(order_number),
        "items": items,
    }

    if source_page and source_page.strip():
        payload["utm_source"] = source_page.strip()[:512]
        payload["utm_medium"] = "store"

    if total_sar is not None:
        payload["price"] = round(float(total_sar) + 1e-9, 2)

    return payload


def rebuild_cod_network_payload_from_persisted_order(order: Order) -> dict[str, Any]:
    lines = [(it.product_id.strip().lower(), it.offer_qty) for it in order.items]
    return build_cod_network_lead_payload(
        customer_name=order.customer_name,
        phone_e164=order.phone_e164,
        phone_digits=order.phone_digits,
        order_number=order.order_number,
        lines=lines,
        source_page=order.source_page,
        total_sar=float(order.total_sar),
    )


def _retries() -> int:
    raw = (os.getenv("COD_NETWORK_RETRIES") or "3").strip()
    try:
        return max(1, min(int(raw), 8))
    except ValueError:
        return 3


def _duplicate_lead_message(body: dict[str, Any]) -> bool:
    for key in ("message", "errors", "log"):
        chunk = body.get(key)
        if isinstance(chunk, str) and "already saved" in chunk.lower():
            return True
        if isinstance(chunk, list):
            for item in chunk:
                if isinstance(item, dict):
                    msg = str(item.get("message") or "")
                    if "already saved" in msg.lower():
                        return True
    return False


def send_cod_network_lead(
    payload: dict[str, Any],
) -> tuple[Literal["ok", "skipped", "failed"], str | None, int | None]:
    if not cod_network_enabled():
        return "skipped", "cod_network_disabled", None

    token = _api_token()
    if not token:
        return "skipped", "no_cod_network_token", None

    base = _api_base()
    if not base:
        return "skipped", "no_cod_network_base_url", None

    url = f"{base}/leads"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "NabtalaboBackend/1.0 (+cod-network leads)",
    }

    retries = _retries()
    last_err: str | None = None

    for attempt in range(retries):
        try:
            with httpx.Client(timeout=25.0, follow_redirects=True) as client:
                resp = client.post(url, json=payload, headers=headers)
        except Exception:
            last_err = "request_error"
            logger.warning(
                "[cod_network] attempt %s/%s connection_error",
                attempt + 1,
                retries,
            )
            if attempt < retries - 1:
                time.sleep(min(8.0, 2**attempt))
                continue
            logger.exception("[cod_network] all retries exhausted (connection)")
            return "failed", last_err, None

        try:
            body = resp.json()
        except Exception:
            body = None

        if resp.is_success and isinstance(body, dict) and body.get("status") == "success":
            lead_id: int | None = None
            data = body.get("data")
            if isinstance(data, dict) and data.get("id") is not None:
                try:
                    lead_id = int(data["id"])
                except (TypeError, ValueError):
                    lead_id = None
            return "ok", None, lead_id

        if isinstance(body, dict) and _duplicate_lead_message(body):
            return "ok", "duplicate_lead", None

        if isinstance(body, dict):
            msg = str(body.get("message") or "api_error")[:400]
            errs = body.get("errors")
            if isinstance(errs, list) and errs:
                first = errs[0]
                if isinstance(first, dict) and first.get("message"):
                    msg = str(first["message"])[:400]
            last_err = f"cod_api:{msg}"
        else:
            last_err = f"http_{resp.status_code}"

        logger.warning(
            "[cod_network] attempt %s/%s status=%s body=%s",
            attempt + 1,
            retries,
            resp.status_code,
            (resp.text or "")[:500],
        )
        if resp.status_code in (408, 429, 500, 502, 503, 504) and attempt < retries - 1:
            time.sleep(min(8.0, 2**attempt))
            continue
        break

    return "failed", last_err or "unknown", None


def apply_cod_network_delivery_to_order(
    order_id: uuid.UUID, payload: dict[str, Any]
) -> None:
    logger.info(
        "[cod_network] SEND_START order_uuid=%s order_id=%s",
        order_id,
        payload.get("order-id"),
    )

    try:
        outcome, err, lead_id = send_cod_network_lead(payload)
    except Exception:
        logger.exception("[cod_network] background send failed order_id=%s", order_id)
        outcome, err, lead_id = "failed", "cod_payload_error", None

    try:
        get_engine()
    except RuntimeError:
        logger.warning("[cod_network] skip_meta_save no engine order_id=%s", order_id)
        return

    db = SessionLocal()
    try:
        persisted = db.get(Order, order_id)
        if persisted is None:
            logger.warning("[cod_network] order_missing order_id=%s", order_id)
            return
        if outcome == "ok":
            persisted.cod_network_sent_at = datetime.now(UTC)
            persisted.cod_network_error = None
            if lead_id is not None:
                persisted.cod_network_lead_id = lead_id
        elif outcome == "failed":
            persisted.cod_network_error = (err or "unknown")[:4000]
        elif outcome == "skipped":
            persisted.cod_network_error = (err or "cod_skipped")[:4000]
        try:
            db.commit()
        except SQLAlchemyError:
            logger.exception("[cod_network] meta_commit_failed order_id=%s", order_id)
            db.rollback()
        else:
            logger.info(
                "[cod_network] SEND_DONE order_uuid=%s order_id=%s outcome=%s lead_id=%s detail=%s",
                order_id,
                payload.get("order-id"),
                outcome,
                lead_id,
                (err[:200] if err else None),
            )
    finally:
        db.close()
