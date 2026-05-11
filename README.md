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

## Cloudflare — **502 Bad Gateway** on `https://api.nabtalabo.store/health`

**502** means Cloudflare did **not** get a valid HTTP response from **your origin** (EasyPanel / the API container). This is **not** CORS and not fixed by frontend code alone.

Check in order:

1. **Backend container is running** (not crash-loop). Logs stuck on `alembic upgrade head` then restart → origin is **down** → **502**. Fix **`DATABASE_URL`**, deploy backend with **`connect_timeout`**, or temporarily **`SKIP_AUTO_MIGRATE=true`** + **`ALLOW_WEAK_START=true`** while you repair Postgres.
2. **Traffic to the container uses port `8000`** (same as `Dockerfile`).
3. **On the VPS / panel network:** `curl -sS http://127.0.0.1:8000/health` (or whatever internal URL the panel uses). If this fails → fix the panel/docker **before** blaming Cloudflare.
4. **SSL mode** in Cloudflare (**SSL/TLS → Overview**): *Flexible* vs *Full (strict)* — wrong mode for how your origin listens often causes **522/525/502** symptoms; align with how EasyPanel terminates TLS.
5. **Purge Cloudflare cache** after the origin is healthy.

Until the origin returns **200** JSON for `/health`, public `https://api.nabtalabo.store/health` can keep showing **502**.

## Google Sheet (orders row)

After each successful `POST /api/orders`, the API can POST one JSON row to **`GOOGLE_SHEET_WEBHOOK_URL`** (Google Apps Script web app). Reference script: **`backend/sheet/google-apps-script-webhook.js`** — paste it into the spreadsheet’s Apps Script editor, deploy as web app, put the URL in `.env`.

## EasyPanel — خضرة الحاوية + الشيك أوت

1. **Health check URL** داخل خدمة الـ API: استعمل **`/health`** أو **`/live`** أو **`/healthz`** (كلها `{"ok":true}` بلا فحص قاعدة). **لا تستعمل `/ready`** إلا إذا Postgres + جدول `orders` جاهزين.
2. **Port** في التعريف والترافيك: **8000** (مثل `Dockerfile`).
3. إذا كان الإقلاع يتوقّف ولّا عدّادك **صفر**: راجع لوغ الدور — غالب **`Alembic upgrade head failed`**.
   - أصلّح **`DATABASE_URL`**؛ أو **`SKIP_AUTO_MIGRATE=true`** مؤقتًا للتشخيص؛ أو **`ALLOW_WEAK_START=true`** لتشغيل الـ API رغم فشل المهاجرة (مؤقت — أصلّح DB بعدها).
4. إذا اللوحة مضبوطة على فحص `/ready` وما عندكش DB ولّ ما بغيتش ضغط صارم: **`READINESS_LITE=true`**.

## Health

- `GET /health` → `{"ok": true}` (مُفضّل لـ EasyPanel)
- `GET /healthz` و `GET /live` → نفس الرد
- `GET /ready` → يفحص Postgres (أو وضع `READINESS_LITE`)

## Status

Starter layout; endpoints and integrations from the architecture doc are expanded incrementally.
