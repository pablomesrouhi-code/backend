"""NabtaLabo FastAPI entrypoint."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

import app.models  # noqa: F401 — register ORM metadata & configure engine when DATABASE_URL is set

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.cors_config import cors_allowed_origins
from app.db_migrate import run_upgrade_head
from app.routers import admin_dashboard as admin_dashboard_router
from app.routers import analytics_collect as analytics_collect_router
from app.routers import capi as capi_router
from app.routers import diagnostics as diagnostics_router
from app.routers import orders as orders_router
from app.routers import cod_network_health as cod_network_health_router
from app.routers import sheet_health as sheet_health_router
from app.services.cod_network import _api_token, cod_network_enabled
from app.services.sheet_webhook import _webhook_url_from_env

logging.basicConfig(level=logging.INFO)


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes")


def _env_falsy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("0", "false", "no")


def _background_migrate() -> bool:
    """When True, run Alembic after the app is accepting traffic (avoids 502 while DB is slow/down).

    Default is **background** when unset so EasyPanel still gets a healthy /health even if APP_ENV
    is missing. Opt out with BACKGROUND_AUTO_MIGRATE=false (blocking migrations before traffic).
    """
    raw = os.getenv("BACKGROUND_AUTO_MIGRATE", "").strip()
    if _env_truthy("BACKGROUND_AUTO_MIGRATE"):
        return True
    if raw and _env_falsy("BACKGROUND_AUTO_MIGRATE"):
        return False
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Apply Alembic migrations (blocking or background — see BACKGROUND_AUTO_MIGRATE)."""
    weak = _env_truthy("ALLOW_WEAK_START")

    async def _migrate_in_thread() -> None:
        try:
            await asyncio.to_thread(run_upgrade_head)
        except Exception:
            logging.exception(
                "[startup] Alembic failed (background) — API is up; fix DATABASE_URL or run migrations manually."
            )

    if _background_migrate():
        logging.info(
            "[startup] BACKGROUND_AUTO_MIGRATE — serving traffic immediately; migrations run in background."
        )
        asyncio.create_task(_migrate_in_thread())
    else:
        try:
            run_upgrade_head()
        except Exception:
            if weak:
                logging.exception(
                    "[startup] Alembic failed but ALLOW_WEAK_START=true — API still starts; fix DATABASE_URL / migrations."
                )
            else:
                raise
    env = os.getenv("APP_ENV", "").strip().lower()
    wh = _webhook_url_from_env()
    if env in ("production", "prod"):
        if wh:
            tail = wh[-44:] if len(wh) > 44 else wh
            logging.info("[sheet] Apps Script webhook configured — …%s", tail)
        else:
            logging.warning(
                "[sheet] GOOGLE_SHEET_WEBHOOK_URL أو SHEET_WEBHOOK_URL فارغ في الإنتاج — الطلبات تُحفظ في Postgres "
                "لكن لا تُرسل إلى Google Sheet. أضِف الرابط /exec في متغيرات **نفس خدمة الـ API** ثم أعد التشغيل."
            )
        if cod_network_enabled() and _api_token():
            logging.info("[cod_network] lead push enabled (POST …/seller/leads)")
        elif cod_network_enabled():
            logging.warning(
                "[cod_network] COD_NETWORK_ENABLED but COD_NETWORK_API_TOKEN missing — leads will not be sent."
            )
    yield


app = FastAPI(title="NabtaLabo API", lifespan=lifespan)

_origins = cors_allowed_origins()
logging.info("[cors] allow_origins count=%s", len(_origins))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(capi_router.router, prefix="/capi", tags=["capi"])
app.include_router(orders_router.router, prefix="/api", tags=["orders"])
app.include_router(diagnostics_router.router, prefix="/api", tags=["diagnostics"])
app.include_router(sheet_health_router.router, prefix="/api", tags=["sheet"])
app.include_router(cod_network_health_router.router, prefix="/api", tags=["cod-network"])
app.include_router(analytics_collect_router.router, prefix="/api", tags=["analytics"])
app.include_router(admin_dashboard_router.router, prefix="/api", tags=["admin"])


class HealthResponse(BaseModel):
    ok: bool = True


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    """Alias for platforms that expect /healthz (same as /health)."""
    return HealthResponse()


@app.get("/live", response_model=HealthResponse)
def live() -> HealthResponse:
    """Liveness probe — process is up; does not check Postgres."""
    return HealthResponse()


@app.get(
    "/sheet-webhook-status",
    response_model=sheet_health_router.SheetWebhookStatus,
)
def sheet_webhook_status_root_compat() -> sheet_health_router.SheetWebhookStatus:
    """Same JSON as `/api/sheet-webhook-status` for probes outside the `/api` prefix."""

    return sheet_health_router.sheet_webhook_status_root()


def _readiness_lite() -> bool:
    """Panels that probe `/ready` but you skip Postgres: set READINESS_LITE=true (EasyPanel green)."""
    return os.getenv("READINESS_LITE", "").strip().lower() in ("1", "true", "yes")


@app.get("/ready", response_model=HealthResponse)
def ready() -> HealthResponse:
    """Postgres check. Use `/health` for process-only probes. Set READINESS_LITE=true to skip DB when unused."""
    logger = logging.getLogger(__name__)
    if _readiness_lite():
        try:
            from app.database import get_engine

            eng = get_engine()
        except RuntimeError:
            logger.info("[ready] READINESS_LITE: no DATABASE_URL — probe ok")
            return HealthResponse()
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("[ready] READINESS_LITE: SELECT 1 ok (orders table not checked)")
            return HealthResponse()
        except Exception:
            logger.exception("[ready] READINESS_LITE: database unreachable")
            raise HTTPException(
                status_code=503,
                detail="READINESS_LITE set but cannot run SELECT 1 — fix DATABASE_URL",
            ) from None

    try:
        from app.database import get_engine

        eng = get_engine()
    except RuntimeError:
        logger.warning("[ready] DATABASE_URL missing — Postgres routes will 503")
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL not set — set internal Postgres URL in backend env",
        ) from None
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
            orders_ok = conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = :t)"
                ),
                {"s": "public", "t": "orders"},
            ).scalar()
            if not orders_ok:
                logger.error(
                    "[ready] connected but public.orders table is missing — run alembic on this DATABASE_URL"
                )
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Postgres reachable but orders table missing — migrations not applied "
                        "(alembic upgrade head) or wrong database name vs PgWeb"
                    ),
                )
            col_ok = conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t AND column_name = :c)"
                ),
                {"s": "public", "t": "orders", "c": "cod_network_lead_id"},
            ).scalar()
            if not col_ok:
                logger.error(
                    "[ready] orders table exists but cod_network_* columns missing — "
                    "apply migration 0003 (alembic upgrade head)"
                )
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "orders table is outdated — run `alembic upgrade head` on this DATABASE_URL "
                        "(revision 0003 adds cod_network_lead_id / cod_network_sent_at / cod_network_error)."
                    ),
                )
    except HTTPException:
        raise
    except Exception:
        logger.exception("[ready] database connection failed")
        raise HTTPException(
            status_code=503,
            detail="Cannot reach Postgres — check DATABASE_URL host, DB name nabtalabo, network",
        ) from None
    return HealthResponse()


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "nabtalabo-api", "docs": "/docs"}


@app.get("/admin")
def admin_shortcut() -> RedirectResponse:
    """Shortcut to the admin UI served at `/api/admin`."""
    return RedirectResponse(url="/api/admin", status_code=307)
