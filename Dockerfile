FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app app

COPY payment_service ./payment_service
COPY alembic.ini .
COPY alembic ./alembic

USER app

EXPOSE 8000

CMD ["python", "-m", "payment_service.main"]
