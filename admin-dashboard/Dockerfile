# ==============================================================================
# Stage 1: Frontend Builder (Preact + Vite + Tailwind v4 -> ~47 kB gzipped SPA)
# ==============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ==============================================================================
# Stage 2: Python Dependency Builder (Compiles psutil in isolated Alpine venv)
# ==============================================================================
FROM python:3.11-alpine AS py-builder

WORKDIR /build
RUN apk add --no-cache gcc musl-dev linux-headers binutils

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt && \
    # Strip build-only packaging tools (pip, setuptools, wheel) from production venv
    rm -rf /opt/venv/lib/python3.11/site-packages/pip* \
           /opt/venv/lib/python3.11/site-packages/setuptools* \
           /opt/venv/lib/python3.11/site-packages/wheel* \
           /opt/venv/lib/python3.11/site-packages/pkg_resources* \
           /opt/venv/lib/python3.11/site-packages/_distutils_hack* \
           /opt/venv/lib/python3.11/site-packages/distutils-precedence.pth \
           /opt/venv/bin/pip* \
           /opt/venv/bin/wheel* && \
    # Strip tests, caches, bytecode, and debug symbols from C-extensions
    find /opt/venv -type d \( -name "__pycache__" -o -name "tests" -o -name "test" \) -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*.a" -o -name "*.h" \) -delete && \
    find /opt/venv -type f -name "*.so*" -exec strip --strip-unneeded {} + 2>/dev/null || true

# ==============================================================================
# Stage 3: Ultra-Minimal Production Runtime (Alpine + venv + Preact static dist)
# ==============================================================================
FROM python:3.11-alpine

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Install only minimal runtime packages (Alpine ffmpeg avoids ~300 MB Debian X11/PulseAudio bloat)
RUN apk add --no-cache bash curl ffmpeg && \
    rm -rf /var/cache/apk/* /tmp/* /var/tmp/* /usr/share/man /usr/share/doc

# Copy stripped Python virtualenv
COPY --from=py-builder /opt/venv /opt/venv

# Copy compiled Preact SPA static bundle (~208 kB uncompressed / ~47 kB gzipped)
COPY --from=frontend-builder /src/static/dist /app/static/dist

# Copy only production backend & static runtime assets (zero Node.js, zero templates, zero frontend src)
COPY app.py ops_resources.py ops_updates.py ./
COPY static/manifest.json static/sw.js ./static/
COPY scripts/backup.sh ./scripts/backup.sh

RUN chmod +x ./scripts/backup.sh && mkdir -p data logs

EXPOSE 5001

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5001", "--workers", "1", "--log-level", "warning"]
