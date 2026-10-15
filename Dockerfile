# Образ add-on'а. Контекст сборки - корень репозитория: внутрь нужны и ядро, и add-on.
# Сначала собирается фронт, потом рабочий образ с бэкендом.
# BUILD_VERSION и BUILD_ARCH передают Supervisor (локальная сборка)
# и GitHub Actions (готовые образы).
ARG BUILD_VERSION=dev
ARG BUILD_ARCH=amd64

FROM node:22-alpine AS frontend
ARG BUILD_VERSION
WORKDIR /build
COPY addon/frontend/package.json addon/frontend/package-lock.json* ./
RUN npm ci
COPY addon/frontend ./
RUN APP_VERSION="$BUILD_VERSION" npm run build

# slim, а не alpine: для pydantic и aiohttp есть готовые колёса, ничего не компилируется.
FROM python:3.13-slim
ARG BUILD_VERSION
ARG BUILD_ARCH

WORKDIR /app
# Ядро и бэкенд ставятся как обычные пакеты, по очереди:
# бэкенд требует plant-control, и к этому моменту он уже установлен из исходников.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ./

COPY addon/backend/pyproject.toml ./addon/backend/
COPY addon/backend/src ./addon/backend/src
RUN pip install --no-cache-dir ./addon/backend

# Собранный фронт: бэкенд отдаёт его как статику.
COPY --from=frontend /build/dist /app/static
COPY run.py /app/run.py

ENV PLANT_CONTROL_DATA_DIR=/data \
    PLANT_CONTROL_STATIC_DIR=/app/static \
    PYTHONUNBUFFERED=1

# По io.hass.version Supervisor узнаёт версию установленного образа.
LABEL io.hass.name="PlantControl" \
      io.hass.description="Targeted plant watering for Home Assistant" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.type="addon" \
      io.hass.url="https://github.com/Mkilord/plant-control" \
      org.opencontainers.image.source="https://github.com/Mkilord/plant-control" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="${BUILD_VERSION}"

EXPOSE 8099
CMD ["python", "/app/run.py"]
