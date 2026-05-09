# NabtaLabo API (backend)

Python **FastAPI** service for NabtaLabo storefront: orders, fraud checks, webhooks, and tracking integrations.

See `docs/` in the monorepo project spec for full architecture (`08-backend-architecture.md`).

## Docker (Postgres + API)

From repo root:

```bash
docker compose up --build
```

Uses service hostname **`nabtalabo_database`** inside the Compose network (EasyPanel uses the same internal DNS pattern). Postgres is mapped to host port **5433**. If **`alembic upgrade head`** fails at startup, **the API exits** — fix `DATABASE_URL` or migrations before deploying.

## Database migrations

Requires PostgreSQL and **`DATABASE_URL`** (SQLAlchemy URL). Les URLs du type `postgres://…` ou `postgresql://…` sont **normalisées** vers `postgresql+psycopg://…` au démarrage.

Au **démarrage de l’API**, Alembic exécute automatiquement **`upgrade head`** avant d’accepter du trafic. En cas d’échec, le processus s’arrête (fail-fast). Pour désactiver temporairement : **`SKIP_AUTO_MIGRATE=true`**.

En local (sans lancer l’API), tu peux toujours faire :

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL
alembic upgrade head
```

## Local run

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env    # configure before production
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Orders (database)

`POST /api/orders` creates an order in Postgres (totals **recalculated server-side**).

Example body:

```json
{
  "customer_name": "Sara",
  "phone": "0551234567",
  "items": [{ "product_id": "rawnaq-c", "offer_qty": 1 }],
  "accepted_upsell": false
}
```

Product IDs: `rawnaq-c`, `khiffabiotic`, `laylmag`. Sum of `offer_qty` must be **1, 2, or 3** for bundle pricing. Try it in **`/docs`**.

Set **`CORS_ORIGINS`** (comma-separated) so the frontend domain can call this API from the browser.

## Health

`GET /health` → `{"ok": true}`

## Status

Starter layout; endpoints and integrations from the architecture doc are expanded incrementally.
