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
from app.services.catalog import resolve_product, resolve_sku
from app.services.sheet_webhook import sheet_order_public_id

logger = logging.getLogger(__name__)

DEFAULT_COD_SKU = "MP-39GYGBTANIO7"
_cached_default_sku: str | None = None


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


def default_cod_sku() -> str:
    """Seller SKU from ``COD_NETWORK_DEFAULT_SKU`` (defaults to the Rawnaq-C seller SKU)."""

    global _cached_default_sku
    if _cached_default_sku:
        return _cached_default_sku

    explicit = (os.getenv("COD_NETWORK_DEFAULT_SKU") or DEFAULT_COD_SKU).strip()
    if not explicit:
        raise ValueError("COD_NETWORK_DEFAULT_SKU is empty")
    _cached_default_sku = explicit
    return explicit


def _sku_overrides() -> dict[str, str]:
    """``COD_NETWORK_SKU_OVERRIDES=rawnaq-c:RWCFH,shahr-hadi:XXXX`` — wins over catalog."""

    raw = (os.getenv("COD_NETWORK_SKU_OVERRIDES") or "").strip()
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split(","):
        chunk = part.strip()
        if not chunk or ":" not in chunk:
            continue
        pid, sku = chunk.split(":", 1)
        pid_k = pid.strip().lower()
        sku_v = sku.strip()
        if pid_k and sku_v:
            out[pid_k] = sku_v
    return out


def resolve_cod_sku(product_id: str) -> str:
    key = product_id.strip().lower()
    overrides = _sku_overrides()
    if key in overrides:
        return overrides[key]
    # Live COD accounts often still use the legacy default for Rawnaq-C.
    if key == "rawnaq-c":
        env_default = (os.getenv("COD_NETWORK_DEFAULT_SKU") or "").strip()
        if env_default:
            return env_default
    return resolve_sku(key)


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


def _phone_variants(phone_e164: str, phone_digits: str) -> list[str]:
    """COD Network sellers sometimes expect +E.164, sometimes bare 966…"""

    primary = _phone_e164(phone_e164, phone_digits)
    variants = [primary]
    bare = primary[1:] if primary.startswith("+") else primary
    if bare and bare not in variants:
        variants.append(bare)
    d = "".join(ch for ch in (phone_digits or "") if ch.isdigit())
    if d.startswith("05") and len(d) >= 10:
        local = d
        if local not in variants:
            variants.append(local)
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


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

    total_qty = 0
    by_sku: dict[str, int] = {}
    for product_id, qty in lines:
        pid = product_id.strip().lower()
        resolve_product(pid)
        q = int(qty)
        if q < 1:
            continue
        sku = resolve_cod_sku(pid)
        by_sku[sku] = by_sku.get(sku, 0) + q
        total_qty += q
    if total_qty < 1:
        raise ValueError("empty items for COD Network lead")

    items = [{"sku": sku, "quantity": quantity} for sku, quantity in by_sku.items()]
    public_id = sheet_order_public_id(order_number)

    payload: dict[str, Any] = {
        "phone": _phone_e164(phone_e164, phone_digits),
        "customer_name": customer_name.strip(),
        # Both keys — older/newer COD Network docs disagree on the field name.
        "order-id": public_id,
        "order_id": public_id,
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


def resend_persisted_order_to_cod_network(
    order: Order,
) -> tuple[Literal["ok", "skipped", "failed"], str | None, int | None]:
    payload = rebuild_cod_network_payload_from_persisted_order(order)
    return send_cod_network_lead(payload)


def mark_order_cod_delivery(
    order: Order,
    outcome: Literal["ok", "skipped", "failed"],
    err: str | None,
    lead_id: int | None,
) -> None:
    if outcome == "ok":
        order.cod_network_sent_at = datetime.now(UTC)
        order.cod_network_error = None
        if lead_id is not None:
            order.cod_network_lead_id = lead_id
    elif outcome == "failed":
        order.cod_network_error = (err or "unknown")[:4000]
    elif outcome == "skipped":
        order.cod_network_error = (err or "cod_skipped")[:4000]


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


def _extract_lead_id(body: dict[str, Any]) -> int | None:
    data = body.get("data")
    if isinstance(data, dict) and data.get("id") is not None:
        try:
            return int(data["id"])
        except (TypeError, ValueError):
            return None
    if body.get("id") is not None:
        try:
            return int(body["id"])
        except (TypeError, ValueError):
            return None
    return None


def _is_success_body(resp: httpx.Response, body: Any) -> tuple[bool, int | None]:
    """Treat common COD Network success shapes as OK (status casing / HTTP-only)."""

    if isinstance(body, dict) and _duplicate_lead_message(body):
        return True, _extract_lead_id(body)

    if not resp.is_success:
        return False, None

    if not isinstance(body, dict):
        # Some gateways return 200/201 with empty body
        return resp.status_code in (200, 201), None

    status = str(body.get("status") or body.get("result") or "").strip().lower()
    if status in ("success", "ok", "true", "1", "created"):
        return True, _extract_lead_id(body)

    if body.get("success") is True:
        return True, _extract_lead_id(body)

    if _extract_lead_id(body) is not None and status not in ("error", "fail", "failed"):
        return True, _extract_lead_id(body)

    return False, None


def _error_from_body(resp: httpx.Response, body: Any) -> str:
    if isinstance(body, dict):
        msg = str(body.get("message") or body.get("error") or "api_error")[:400]
        errs = body.get("errors")
        if isinstance(errs, list) and errs:
            first = errs[0]
            if isinstance(first, dict) and first.get("message"):
                msg = str(first["message"])[:400]
            elif isinstance(first, str):
                msg = first[:400]
        elif isinstance(errs, dict):
            # e.g. {"sku":["invalid"]}
            parts = []
            for k, v in list(errs.items())[:4]:
                parts.append(f"{k}:{v}")
            if parts:
                msg = f"{msg} ({'; '.join(parts)})"[:400]
        return f"cod_api:{msg}"
    return f"http_{resp.status_code}:{(resp.text or '')[:200]}"


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

    # Try primary phone, then bare 966… if API rejects phone format.
    phone_list = _phone_variants(
        str(payload.get("phone") or ""),
        "",
    )
    if not phone_list and payload.get("phone"):
        phone_list = [str(payload["phone"])]

    retries = _retries()
    last_err: str | None = None
    attempt_payload = dict(payload)

    for phone in phone_list or [str(payload.get("phone") or "")]:
        attempt_payload = dict(payload)
        attempt_payload["phone"] = phone

        for attempt in range(retries):
            try:
                with httpx.Client(timeout=25.0, follow_redirects=True) as client:
                    resp = client.post(url, json=attempt_payload, headers=headers)
            except Exception:
                last_err = "request_error"
                logger.warning(
                    "[cod_network] attempt %s/%s connection_error phone=%s",
                    attempt + 1,
                    retries,
                    phone[:6] + "***",
                )
                if attempt < retries - 1:
                    time.sleep(min(8.0, 2**attempt))
                    continue
                logger.exception("[cod_network] all retries exhausted (connection)")
                break

            try:
                body = resp.json()
            except Exception:
                body = None

            ok, lead_id = _is_success_body(resp, body)
            if ok:
                return "ok", None, lead_id

            last_err = _error_from_body(resp, body)
            logger.warning(
                "[cod_network] attempt %s/%s status=%s phone=%s sku=%s body=%s",
                attempt + 1,
                retries,
                resp.status_code,
                phone[:6] + "***",
                ",".join(i.get("sku", "") for i in (attempt_payload.get("items") or [])),
                (resp.text or "")[:500],
            )

            # Phone-format errors → try next phone variant immediately
            err_l = (last_err or "").lower()
            if any(x in err_l for x in ("phone", "mobile", "رقم")) and phone != phone_list[-1]:
                break

            if resp.status_code in (408, 429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(min(8.0, 2**attempt))
                continue
            break
        else:
            continue
        # if we broke due to phone error, continue outer phone loop
        if last_err and any(x in last_err.lower() for x in ("phone", "mobile", "رقم")):
            continue
        break

    return "failed", last_err or "unknown", None


def probe_cod_network_api() -> dict[str, Any]:
    """Live check: token + optional products list (does not create a lead)."""

    token = _api_token()
    base = _api_base()
    out: dict[str, Any] = {
        "enabled": cod_network_enabled(),
        "token_configured": bool(token),
        "base": base or None,
        "default_sku": None,
        "sku_overrides": _sku_overrides(),
        "http_ok": False,
        "sample_skus": [],
        "probe_error": None,
    }
    try:
        out["default_sku"] = default_cod_sku()
    except Exception as e:
        out["probe_error"] = str(e)[:300]
        return out

    if not token or not base:
        out["probe_error"] = "missing_token_or_base"
        return out

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "NabtalaboBackend/1.0 (+cod-network probe)",
    }
    # Try common product list endpoints; ignore 404 and keep going.
    for path in ("/products", "/marketplace/products", "/offers"):
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(f"{base}{path}", headers=headers)
        except Exception as e:
            out["probe_error"] = f"request_error:{e}"[:300]
            continue
        if resp.status_code == 404:
            continue
        out["http_ok"] = resp.is_success
        if not resp.is_success:
            out["probe_error"] = f"http_{resp.status_code}:{(resp.text or '')[:180]}"
            continue
        try:
            body = resp.json()
        except Exception:
            out["probe_error"] = f"non_json_from_{path}"
            continue
        # Collect a few SKUs if present
        rows = body.get("data") if isinstance(body, dict) else body
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("items") or rows.get("products") or []
        if isinstance(rows, list):
            skus = []
            for row in rows[:30]:
                if not isinstance(row, dict):
                    continue
                sku = row.get("sku") or row.get("SKU") or row.get("reference")
                if sku:
                    skus.append(str(sku))
            out["sample_skus"] = skus[:15]
            out["probe_error"] = None
            out["probed_path"] = path
            return out
        out["probe_error"] = None
        out["probed_path"] = path
        return out

    if not out["http_ok"] and not out["probe_error"]:
        out["probe_error"] = "no_products_endpoint"
    return out


def apply_cod_network_delivery_to_order(
    order_id: uuid.UUID, payload: dict[str, Any]
) -> tuple[Literal["ok", "skipped", "failed"], str | None, int | None]:
    skus = ",".join(item["sku"] for item in payload.get("items") or [])
    logger.info(
        "[cod_network] SEND_START order_uuid=%s order_id=%s sku=%s",
        order_id,
        payload.get("order-id") or payload.get("order_id"),
        skus or default_cod_sku(),
    )

    try:
        outcome, err, lead_id = send_cod_network_lead(payload)
    except Exception:
        logger.exception("[cod_network] send failed order_id=%s", order_id)
        outcome, err, lead_id = "failed", "cod_payload_error", None

    try:
        get_engine()
    except RuntimeError:
        logger.warning("[cod_network] skip_meta_save no engine order_id=%s", order_id)
        return outcome, err, lead_id

    db = SessionLocal()
    try:
        persisted = db.get(Order, order_id)
        if persisted is None:
            logger.warning("[cod_network] order_missing order_id=%s", order_id)
            return outcome, err, lead_id
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
                payload.get("order-id") or payload.get("order_id"),
                outcome,
                lead_id,
                (err[:200] if err else None),
            )
    finally:
        db.close()

    return outcome, err, lead_id
