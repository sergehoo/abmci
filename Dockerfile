# ====== Stage 1: build deps ======
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

WORKDIR /app

# OS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Requirements
COPY requirements.txt /app/requirements.txt
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels

# ====== Stage 2: runtime ======
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=abmci.settings \
    PORT=8000

WORKDIR /app

# OS deps (runtime only)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*

# App code
COPY . /app

# Entrypoint
#COPY docker/entrypoint.sh /entrypoint.sh
#RUN chmod +x /entrypoint.sh

# Create static/media dirs (mounted by volumes anyway)
RUN mkdir -p /app/staticfiles /app/media

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
# Démarre Daphne (Channels)
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "abmci.asgi:application"]