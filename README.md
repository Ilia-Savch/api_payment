# API платежей

Python 3.11+, FastAPI, Pydantic v2. Целевая БД — PostgreSQL.

Текущий этап: каркас приложения, конфигурация, инструменты проверки и
[контракт API](docs/API_CONTRACT.md). БД, Docker и платёжные маршруты
реализуются на следующих этапах.

## Запуск

Из корня репозитория, PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe -m payment_service.main
```

Linux / macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python -m payment_service.main
```

Для запуска без инструментов разработки достаточно `requirements.txt`.
Swagger UI: <http://localhost:8000/docs>, OpenAPI: <http://localhost:8000/openapi.json>.

## Конфигурация

По образцу `config.py` используются вложенные Pydantic Settings.
`.env` читается из текущего рабочего каталога; команды выполняются из корня проекта.
Переменные окружения имеют приоритет над `.env`.

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `RUN__HOST` | `0.0.0.0` | Адрес HTTP-сервера |
| `RUN__PORT` | `8000` | Порт от 1 до 65535 |
| `LOGGING__LOG_LEVEL` | `info` | Уровень логов Uvicorn: `debug`, `info`, `warning`, `error`, `critical` |

`.env` исключён из Git. В `.env.example` находятся только настройки без секретов.
Бизнес-события и подключение к PostgreSQL добавляются на соответствующих этапах.

## Проверки

PowerShell:

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m mypy
.venv\Scripts\python.exe -m pytest
```

При активированном виртуальном окружении и установленном GNU Make:

```sh
make check
```

`make check` выполняет те же четыре команды. В Linux / macOS без Make можно
использовать `.venv/bin/python -m ...` с теми же аргументами.

Текущие тесты проверяют доступность OpenAPI через ASGI-запрос httpx,
загрузку UTF-8 `.env`, приоритет окружения и ошибки конфигурации.
Тесты бизнес-логики добавляются вместе с её реализацией.

## Структура

- `payment_service/main.py` — приложение и запуск Uvicorn.
- `api/api_v1/endpoints` — HTTP-схемы и ответы; `router.py` собирает маршруты без префикса.
- `api/api_v1/dependencies` — зависимости запросов.
- `api/api_v1/crud` — запросы к БД, без самостоятельного commit.
- `core/config.py` — конфигурация из окружения.
- `core/models` — ORM-модели и работа с сессиями.
- `core/schemas` — Pydantic-схемы API.
- `services` — бизнес-правила и границы транзакций.
- `tests` — тесты; `docs/API_CONTRACT.md` — проверочный список ТЗ.

Ветка для новой функциональности: `<название-по-смыслу>-feature`,
для исправлений: `<название-по-смыслу>-fix`.
