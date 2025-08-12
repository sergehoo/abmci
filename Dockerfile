# ====== Stage 1: build deps ======
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

WORKDIR /app

# 🔧 Outils de build + headers pour compiler d’éventuelles wheels natives
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gdal-bin libgdal-dev \
    libgeos-dev \
    proj-bin libproj-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels


# ====== Stage 2: runtime ======
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=abmci.settings \
    PORT=8000

WORKDIR /app

# 🔧 Librairies *runtime* (il faut GDAL/GEOS/PROJ ici aussi !)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl ca-certificates \
    gdal-bin libgdal-dev \
    libgeos-dev \
    proj-bin libproj-dev \
    && rm -rf /var/lib/apt/lists/*

# Wheels construites
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*

# Code
COPY . /app

# Entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Dossiers statiques
RUN mkdir -p /app/staticfiles /app/media

# 💡 Expose les chemins des libs pour éviter les "Could not find the GDAL library"
# AMD64 (x86_64)
ENV GDAL_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgdal.so \
    GEOS_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgeos_c.so

# Si tu es sur ARM64 (Graviton/RPi), commente les 2 lignes ci-dessus et décommente celles-ci :
# ENV GDAL_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/libgdal.so \
#     GEOS_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/libgeos_c.so

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]

# ✅ Recommandé avec Channels: daphne
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "abmci.asgi:application"]

# 👉 Alternative si tu veux absolument gunicorn (ASGI) :
# CMD ["gunicorn", "abmci.asgi:application", "--bind=0.0.0.0:8000", "--workers=4", "--worker-class=uvicorn.workers.UvicornWorker", "--timeout=180", "--access-logfile=-", "--error-logfile=-", "--capture-output", "--log-level=info"]