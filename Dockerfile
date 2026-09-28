# Образ add-on'а. Контекст сборки - корень репозитория: внутрь нужны и ядро, и add-on.
# Сначала собирается фронт, потом рабочий образ с бэкендом.
FROM node:22-alpine AS frontend
WORKDIR /build
COPY addon/frontend/package.json addon/frontend/package-lock.json* ./
RUN npm install
COPY addon/frontend ./
RUN npm run build

# slim, а не alpine: для pydantic и aiohttp есть готовые колёса, ничего не компилируется.
FROM python:3.13-slim

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

EXPOSE 8099
CMD ["python", "/app/run.py"]
