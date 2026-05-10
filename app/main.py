"""NabtaLabo FastAPI entrypoint."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

import app.models  # noqa: F401 — register ORM metadata & configure engine when DATABASE_URL is set

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.cors_config import cors_allowed_origins
from app.db_migrate import run_upgrade_head
from app.routers import capi as capi_router
from app.routers import orders as orders_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Apply Alembic migrations to head before serving (see app/db_migrate.py)."""
    run_upgrade_head()
    env = os.getenv("APP_ENV", "").strip().lower()
    sheet_url = (os.getenv("GOOGLE_SHEET_WEBHOOK_URL") or "").strip()
    if env in ("production", "prod") and not sheet_url:
        logging.warning(
            "[sheet] GOOGLE_SHEET_WEBHOOK_URL فارغ في الإنتاج — الطلبات تُحفظ في Postgres لكن لا تُرسل إلى Google Sheet حتى تضيف الرابط وتعيد تشغيل الـ API"
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


class HealthResponse(BaseModel):
    ok: bool = True


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "nabtalabo-api", "docs": "/docs"}
