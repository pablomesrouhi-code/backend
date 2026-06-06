FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
# Fail Docker build if admin HTML is missing (avoids 500 from TemplateResponse / missing template).
RUN test -f app/templates/admin_dashboard.html
# Fail Docker build immediately if upstream deploy missed new modules (easier than a crash-loop in prod).
RUN test -f app/log_safe.py
RUN test -f app/services/capi_dispatch.py
RUN test -f app/services/cod_network.py

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
