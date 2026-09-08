FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 changeapi \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin changeapi

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY change_api ./change_api

USER 10001:10001
EXPOSE 8080

CMD ["uvicorn", "change_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
