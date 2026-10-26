# API платежей

API оплаты курсов на FastAPI, Pydantic v2, SQLAlchemy 2 и PostgreSQL 16.
Все суммы — целые копейки. `KVITTO10` даёт скидку 10% без учёта регистра.
Доступны `card`, `sbp` и рассрочка на 3, 6 или 12 месяцев.

## Запуск

Нужен Docker с Compose. Команды ниже выполняются из корня проекта в Bash
(Linux, macOS или Git Bash в Windows).

```bash
cp .env.example .env
```

В `.env` заполни `DB__PASSWORD` и `WEBHOOK_SECRET` своими случайными значениями.
Остальные настройки можно оставить как в примере. `.env` исключён из Git.

```bash
docker compose up -d --build --wait
```

Compose поднимет БД, применит миграции Alembic и запустит приложение.
Swagger: http://localhost:8000/docs. Логи: `docker compose logs -f app`.
Остановка: `docker compose down`. Данные БД сохраняются в Docker volume.

## Настройки

Настройки читаются из `.env`; переменные окружения имеют приоритет.
`RUN__PORT` — порт API, по умолчанию 8000. `DB__PORT` — порт PostgreSQL на
компьютере, по умолчанию 5432; если он занят, выбери другой.
`DB__NAME` и `DB__USER` по умолчанию равны `payments`.
`LOGGING__LOG_LEVEL` задаёт уровень логов, по умолчанию `info`.

Цены задаются через `TARIFFS__BASIC_PRICE`, `TARIFFS__STANDARD_PRICE` и
`TARIFFS__PREMIUM_PRICE`: по умолчанию 990000, 1990000 и 2990000 копеек.
Они обновляются при запуске приложения. Суммы старых платежей сохраняются.

`WEBHOOK_SECRET` — общий секрет отправителя вебхука и сервера.
Без непустого секрета приложение не запускается.

## Проверки

Для локальных тестов нужен Python 3.11+; в Docker и CI используется 3.12.
Создай окружение и установи зависимости.
В Git Bash на Windows вместо `source .venv/bin/activate` используй
`source .venv/Scripts/activate`.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Для тестов подними отдельную PostgreSQL:

```bash
DB__NAME=payments_test DB__USER=payments_test DB__PASSWORD=synthetic-test-password DB__PORT=55432 \
  docker compose -p api-payment-tests up -d --wait postgres
export TEST_DATABASE_URL='postgresql+asyncpg://payments_test:synthetic-test-password@127.0.0.1:55432/payments_test'
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
docker compose -p api-payment-tests stop postgres
```

При установленном Make четыре проверки можно заменить на `make check`.
Без `TEST_DATABASE_URL` проверки БД пропускаются. Имя тестовой базы должно
оканчиваться на `_test`; миграции в ней применяются автоматически.
GitHub Actions запускает проверки на каждый push с отдельной БД.

## Примеры запросов

Если изменён `RUN__PORT`, подставь свой порт. Сначала получи ID тарифов:

```bash
curl -s http://localhost:8000/tariffs
```

Подставь нужный `tariff_id` вместо 1. Сервер сам вычислит сумму, скидку и график:

```bash
curl -i http://localhost:8000/payments \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-payment-1' \
  -d '{"tariff_id":1,"email":"payer@example.com","method":"installment","installment_months":3,"promo_code":"kvitto10"}'
```

Первый запрос вернёт `201` и платёж со статусом `pending`, повтор с тем же
ключом — тот же платёж с `200`. Без ключа каждый запрос создаёт новый платёж.
Подставь полученный ID вместо 1:

```bash
PAYMENT_ID=1
curl -s "http://localhost:8000/payments/$PAYMENT_ID"
curl -sG http://localhost:8000/payments \
  --data-urlencode 'email=payer@example.com' --data-urlencode 'status=pending'
```

Вебхук требует HMAC-SHA256 в заголовке `X-Signature`: 64 hex-символа без префикса.
В примере подпись вычисляется внутри контейнера с его `WEBHOOK_SECRET`:

```bash
BODY="{\"payment_id\":$PAYMENT_ID,\"status\":\"succeeded\"}"
SIGNATURE=$(printf '%s' "$BODY" | docker compose exec -T app python -c '
import hmac, sys
from payment_service.core.config import get_settings
print(hmac.digest(get_settings().webhook_secret.get_secret_value().encode(), sys.stdin.buffer.read(), "sha256").hex())
')
curl -i http://localhost:8000/webhooks/bank \
  -H 'Content-Type: application/json' -H "X-Signature: $SIGNATURE" \
  --data-binary "$BODY"
```

После расчёта подписи тело менять нельзя, включая пробелы и переносы строк.
Успех — `200 {"result":"ok"}`. Разрешены только `pending → succeeded`,
`pending → failed`, `succeeded → refunded`. Остальные переходы, включая повтор
статуса, дают `409 {"error":"invalid_transition"}`. Неверная подпись — `401`,
неизвестный платёж — `404`, ошибки валидации — стандартный `422` FastAPI.

Полный контракт — [docs/API_CONTRACT.md](docs/API_CONTRACT.md).
Работа с ИИ описана в [AI_LOG.md](AI_LOG.md).
