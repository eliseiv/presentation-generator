import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from api.lifespan import app_lifespan
from api.middlewares import ServiceApiKeyMiddleware, UserConfigEnvUpdateMiddleware
from api.v1.auth.router import API_V1_AUTH_ROUTER
from api.v1.billing.router import BILLING_ROUTER
from api.v1.mock.router import API_V1_MOCK_ROUTER
from api.v1.ppt.router import API_V1_PPT_ROUTER
from api.v1.webhook.router import API_V1_WEBHOOK_ROUTER
from utils.get_env import get_app_data_directory_env
from utils.path_helpers import get_resource_path


OPENAPI_DESCRIPTION = """
Постарался расписать все красиво

Файлы результата хранятся на сервере ограниченное время: TTL 2 часа.

## Допустимые Значения Параметров

### `template` — шаблон оформления

| Значение | Описание |
|---|---|
| `general` *(по умолчанию)* | Универсальный набор: intro, bullets, metrics, table, team, quote. |
| `modern` | Современный pitch-deck: intro pitch, image+text, charts, metrics. |
| `standard` | Деловой, классический: header+counter, splits, team cards. |
| `swift` | Компактный, тезисный: simple bullets, timeline, metrics numbers. |

### `tone` — тон текста

| Значение | Описание |
|---|---|
| `default` *(по умолчанию)* | Нейтральный универсальный тон. |
| `casual` | Разговорный, дружественный. |
| `professional` | Деловой, сдержанный (executives, отчёты). |
| `funny` | Лёгкий с юмором. |
| `educational` | Обучающий, объясняющий шаг за шагом. |
| `sales_pitch` | Продающий, акцент на выгодах. |

### `verbosity` — плотность текста

| Значение | Описание |
|---|---|
| `concise` | Минимум текста, тезисами. |
| `standard` *(по умолчанию)* | Сбалансированный объём. |
| `text-heavy` | Развёрнутые описания, длинные параграфы. |

### `export_as` — формат файла

| Значение | Описание |
|---|---|
| `pptx` *(по умолчанию)* | PowerPoint, редактируемый. |
| `pdf` | PDF для распространения. |

### `language` — язык

Свободная строка с английским названием языка: `English`, `Russian` и т. д.
Если не указано — определяется по содержимому `content`.

### `n_slides` — количество слайдов

Целое число от **1 до 50**. Если `include_table_of_contents=true`,
минимум **3**. Если не указано — модель сама подберёт количество.

### `instructions` — кастомизация

Произвольная строка с дополнительными инструкциями для LLM. Примеры:

- Имя автора: `"Use 'Александр Иванов' as the presenter name."`
- Фокус: `"Focus on practical examples for healthcare professionals."`
- Структура: `"Start with a problem statement, then 3 solutions, then ROI."`

## Источники Контента

Сервис принимает контент из нескольких источников, можно комбинировать:

| Поле | Что внутри | Сценарий |
|---|---|---|
| `content` | строка с темой/текстом | Простой prompt: «AI in healthcare» |
| `slides_markdown` | массив готовых markdown-слайдов | Если текст есть, нужно только видео сгенерировать |
| `files` | пути загруженных файлов | PDF/DOCX/TXT/изображения, а также `.mp4/.mov/.mkv/.webm` и `.mp3/.wav/.m4a` |
| `video_url` | прямая ссылка на видео | Кадры через GPT-4o Vision (1 кадр/10 сек, до 30 мин) |
| `source_url` | ссылка на веб-страницу | Извлечение текста |

## Авторизация и Биллинг

Каждый запрос в API:

1. **`X-API-Key`** — общий сервисный ключ (env `SERVICE_API_KEY`),
   гейт сервиса. Без него — 401.
2. **`X-User-Id`** — идентификатор конкретного пользователя
   (Apple `identifierForVendor` или ваш собственный стабильный UUID).
   Без него `/generate*` вернёт **422**. Любой неизвестный `X-User-Id`
   автоматически создаётся как новый пользователь с балансом **0**
   токенов и `subscription=false`.

### Стоимость генерации

Одна успешная генерация снимает `TOKEN_COST_PER_GENERATION` токенов
(по умолчанию **1**) — одинаково для prompt / video / URL / 3-слайд /
30-слайд. При ошибке генерации токены автоматически возвращаются.

Если токенов не хватает — `/generate*` вернёт **HTTP 402**:

```json
{ "error": "insufficient_tokens", "balance": 0, "required": 1 }
```

### Пополнение баланса

Два пути:

1. **Подписка через Adapty** (основной). Adapty шлёт webhook на
   `/api/v1/billing/adapty/webhook`, мы выставляем `subscription=true`
   и начисляем `SUBSCRIPTION_TOKENS_GRANT` токенов (по умолчанию
   **100**) при `subscription_started` / `subscription_renewed`.
   При `subscription_cancelled` / `subscription_expired` снимается
   только флаг, токены остаются.
2. **Админ-пополнение** через `POST /api/v1/billing/credit` с заголовком
   `X-Admin-Key` (env `ADMIN_API_KEY`, отдельный от SERVICE_API_KEY).

Текущий баланс и состояние подписки видны через
`GET /api/v1/billing/me` с заголовком `X-User-Id`.
"""


OPENAPI_TAGS = [
    {
        "name": "1. Создание презентации",
        "description": "Запуск генерации презентации",
    },
    {
        "name": "2. Проверка статуса",
        "description": "Polling статуса async-задачи до completed или error.",
    },
    {
        "name": "3. Скачивание результата",
        "description": "Скачивание готового PPTX/PDF файла по path из completed-задачи.",
    },
    {
        "name": "4. Загрузка файлов",
        "description": "Опциональная загрузка PDF/DOCX/TXT/изображений как источников.",
    },
    {
        "name": "5. Синхронная генерация",
        "description": "Блокирующая генерация для коротких тестов через Swagger.",
    },
    {
        "name": "6. Кошелёк пользователя",
        "description": (
            "Баланс токенов и состояние подписки конкретного пользователя. "
            "Для всех iOS-эндпоинтов теперь обязателен header `X-User-Id`."
        ),
    },
    {
        "name": "7. Админ-операции",
        "description": (
            "Ручное начисление токенов. Доступно только с правильным "
            "`X-Admin-Key` (env `ADMIN_API_KEY`), отдельным от SERVICE_API_KEY."
        ),
    },
    {
        "name": "8. Adapty webhook",
        "description": (
            "Входящий webhook от Adapty для событий подписки. Подпись HMAC-SHA256 "
            "проверяется против env `ADAPTY_WEBHOOK_SECRET`."
        ),
    },
]

IOS_OPENAPI_PATHS = {
    "/api/v1/ppt/presentation/generate/async": {"post"},
    "/api/v1/ppt/presentation/status/{id}": {"get"},
    "/api/v1/ppt/presentation/generate": {"post"},
    "/api/v1/ppt/files/upload": {"post"},
    "/api/v1/billing/me": {"get"},
    "/api/v1/billing/credit": {"post"},
    "/api/v1/billing/adapty/webhook": {"post"},
}

app = FastAPI(
    title="Presenton Backend API",
    summary="Backend API для генерации AI-презентаций",
    description=OPENAPI_DESCRIPTION,
    version="0.1.0",
    openapi_tags=OPENAPI_TAGS,
    lifespan=app_lifespan,
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
        tags=OPENAPI_TAGS,
    )
    _filter_ios_openapi_paths(openapi_schema)
    _add_download_endpoint_doc(openapi_schema)
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "ServiceApiKey"
    ] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Сервисный API key из переменной окружения SERVICE_API_KEY.",
    }

    for path, path_item in openapi_schema.get("paths", {}).items():
        if path.startswith("/api/"):
            for operation in path_item.values():
                if isinstance(operation, dict):
                    operation.setdefault("security", [{"ServiceApiKey": []}])

    _apply_swagger_examples(openapi_schema)

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


def _filter_ios_openapi_paths(openapi_schema: dict) -> None:
    filtered_paths = {}
    for path, allowed_methods in IOS_OPENAPI_PATHS.items():
        path_item = openapi_schema.get("paths", {}).get(path)
        if not path_item:
            continue
        filtered_path_item = {
            method: operation
            for method, operation in path_item.items()
            if method in allowed_methods
        }
        if filtered_path_item:
            filtered_paths[path] = filtered_path_item

    openapi_schema["paths"] = filtered_paths


def _add_download_endpoint_doc(openapi_schema: dict) -> None:
    openapi_schema.setdefault("paths", {})["/app_data/exports/{file_path}"] = {
        "get": {
            "tags": ["3. Скачивание результата"],
            "summary": "Скачать готовый PPTX/PDF файл",
            "description": (
                "Скачивает файл, путь к которому вернулся в `data.path` после "
                "успешного завершения генерации.\n\n"
                "В Swagger этот endpoint описан для документации. На практике "
                "`file_path` - это часть пути после `/app_data/exports/`.\n\n"
                "Пример: если `data.path` равен "
                "`/app_data/exports/demo/result.pptx`, полный URL будет "
                "`https://appbackendnew.store/app_data/exports/demo/result.pptx`.\n\n"
            ),
            "operationId": "downloadGeneratedPresentationFile",
            "security": [{"ServiceApiKey": []}],
            "parameters": [
                {
                    "name": "file_path",
                    "in": "path",
                    "required": True,
                    "schema": {
                        "type": "string",
                        "example": "d3000f96-096c-4768-b67b-e99aed029b57/result.pptx",
                    },
                    "description": "Путь к файлу внутри `app_data/exports`.",
                }
            ],
            "responses": {
                "200": {
                    "description": "Файл PPTX/PDF.",
                    "content": {
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation": {
                            "schema": {"type": "string", "format": "binary"}
                        },
                        "application/pdf": {
                            "schema": {"type": "string", "format": "binary"}
                        },
                    },
                },
                "401": {
                    "description": "API key не передан или неверный.",
                    "content": {
                        "application/json": {
                            "example": {"detail": "Invalid or missing API key"}
                        }
                    },
                },
                "404": {
                    "description": "Файл не найден или уже удален по TTL.",
                },
            },
        }
    }


def _set_operation(
    openapi_schema: dict,
    path: str,
    method: str,
    *,
    summary: str,
    description: str,
    response_description: str | None = None,
) -> dict | None:
    operation = openapi_schema.get("paths", {}).get(path, {}).get(method)
    if not operation:
        return None

    operation["summary"] = summary
    operation["description"] = description
    if response_description:
        for response in operation.get("responses", {}).values():
            if isinstance(response, dict) and response.get("description") == "Successful Response":
                response["description"] = response_description
    return operation


def _set_json_request_examples(operation: dict, examples: dict) -> None:
    request_body = operation.setdefault("requestBody", {})
    content = request_body.setdefault("content", {})
    content.setdefault("application/json", {}).setdefault("examples", examples)


def _set_json_response_example(
    operation: dict,
    status_code: str,
    *,
    description: str,
    example: dict | list | str,
) -> None:
    responses = operation.setdefault("responses", {})
    response = responses.setdefault(status_code, {"description": description})
    response["description"] = description
    content = response.setdefault("content", {})
    content.setdefault("application/json", {}).setdefault("example", example)


def _set_error_examples(operation: dict, *, include_insufficient_tokens: bool = False) -> None:
    responses = operation.setdefault("responses", {})
    responses["401"] = {
        "description": "API key не передан или неверный.",
        "content": {
            "application/json": {
                "example": {"detail": "Invalid or missing API key"}
            }
        },
    }
    if include_insufficient_tokens:
        responses["402"] = {
            "description": (
                "Недостаточно токенов. iOS должен показать paywall и "
                "повторить попытку после пополнения баланса."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "insufficient_tokens",
                            "balance": 0,
                            "required": 1,
                        }
                    }
                }
            },
        }
        responses["422"] = {
            "description": "Заголовок `X-User-Id` не передан.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "type": "missing",
                                "loc": ["header", "X-User-Id"],
                                "msg": "Field required",
                                "input": None,
                            }
                        ]
                    }
                }
            },
        }
    responses["500"] = {
        "description": "Сервисный ключ не настроен или произошла внутренняя ошибка.",
        "content": {
            "application/json": {
                "examples": {
                    "missing_service_key": {
                        "summary": "SERVICE_API_KEY не настроен",
                        "value": {"detail": "SERVICE_API_KEY is not configured"},
                    },
                    "internal_error": {
                        "summary": "Внутренняя ошибка",
                        "value": {"detail": "Presentation generation failed"},
                    },
                }
            }
        },
    }


def _set_tags(operation: dict, *tags: str) -> None:
    operation["tags"] = list(tags)


def _apply_swagger_examples(openapi_schema: dict) -> None:
    generate_operation = _set_operation(
        openapi_schema,
        "/api/v1/ppt/presentation/generate",
        "post",
        summary="Сгенерировать презентацию синхронно",
        description=(
            "Используйте этот endpoint только для коротких тестов. "
            "Для production-flow лучше использовать `/generate/async`, потому что "
            "генерация может занять десятки секунд или минуты.\n\n"
            "Создает презентацию из текста, Markdown-слайдов или ранее загруженных "
            "файлов. Запрос блокируется до завершения генерации и экспорта.\n\n"
            "Пример curl:\n"
            "```bash\n"
            "curl -X POST https://appbackendnew.store/api/v1/ppt/presentation/generate \\\n"
            "  -H 'X-API-Key: <SERVICE_API_KEY>' \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            "  -d '{\"content\":\"Introduction to Machine Learning\",\"n_slides\":5,"
            "\"language\":\"English\",\"template\":\"general\",\"export_as\":\"pptx\"}'\n"
            "```"
        ),
        response_description="Путь к готовому файлу презентации и ID презентации.",
    )
    if generate_operation:
        _set_tags(generate_operation, "5. Синхронная генерация")
        _set_error_examples(generate_operation, include_insufficient_tokens=True)
        _set_json_request_examples(
            generate_operation,
            {
                "prompt": {
                    "summary": "Генерация из prompt",
                    "description": "Минимальный пример генерации PPTX из темы.",
                    "value": {
                        "content": "Introduction to Machine Learning",
                        "slides_markdown": None,
                        "instructions": "Make it practical and suitable for executives.",
                        "tone": "professional",
                        "verbosity": "standard",
                        "web_search": False,
                        "n_slides": 5,
                        "language": "English",
                        "template": "general",
                        "include_table_of_contents": False,
                        "include_title_slide": True,
                        "files": None,
                        "video_url": None,
                        "source_url": None,
                        "export_as": "pptx",
                        "trigger_webhook": False,
                    },
                },
                "markdown": {
                    "summary": "Генерация из готовых Markdown-слайдов",
                    "value": {
                        "content": "Quarterly business review",
                        "slides_markdown": [
                            "# Q1 Results\n\nRevenue, margin, and growth overview",
                            "## Key Wins\n\n- New markets\n- Better retention\n- Faster onboarding",
                            "## Next Steps\n\n- Expand sales\n- Improve support\n- Optimize costs",
                        ],
                        "language": "English",
                        "template": "general",
                        "export_as": "pdf",
                    },
                },
                "files": {
                    "summary": "Генерация с загруженными файлами",
                    "description": "Сначала загрузите файлы через /api/v1/ppt/files/upload.",
                    "value": {
                        "content": "Create a concise report from uploaded documents",
                        "files": ["/tmp/presenton/abc/source.pdf"],
                        "n_slides": 8,
                        "language": "Russian",
                        "template": "general",
                        "export_as": "pptx",
                    },
                },
                "video_url": {
                    "summary": "Генерация по ссылке на видео",
                    "description": (
                        "Сервис скачает аудио через ffmpeg, транскрибирует "
                        "его через Whisper и опишет 1 кадр в 10 секунд через "
                        "GPT-4o Vision. Лимит длительности — 30 минут."
                    ),
                    "value": {
                        "video_url": "https://dn720706.ca.archive.org/0/items/ElephantsDream/ed_hd.mp4",
                        "n_slides": 5,
                        "language": "Russian",
                        "template": "general",
                        "export_as": "pptx",
                    },
                },
                "video_upload": {
                    "summary": "Генерация по загруженному видео-файлу",
                    "description": (
                        "Сначала загрузите видео через /api/v1/ppt/files/upload "
                        "(допускаются `.mp4`, `.mov`, `.mkv`, `.webm`, "
                        "`.mp3`, `.wav` и др.; до 2 ГБ). Полученный путь "
                        "передаётся в `files` — далее тот же pipeline, что и "
                        "для `video_url`."
                    ),
                    "value": {
                        "files": ["/tmp/presenton/abc/lecture.mp4"],
                        "n_slides": 7,
                        "language": "Russian",
                        "template": "general",
                        "export_as": "pptx",
                    },
                },
                "source_url": {
                    "summary": "Генерация по ссылке на статью / Wikipedia",
                    "description": (
                        "Для `*.wikipedia.org` используется REST API. Для "
                        "других сайтов сервис скачивает HTML и извлекает "
                        "основной текст через trafilatura."
                    ),
                    "value": {
                        "source_url": "https://en.wikipedia.org/wiki/Photosynthesis",
                        "n_slides": 6,
                        "language": "Russian",
                        "template": "general",
                        "export_as": "pptx",
                    },
                },
                "url_with_focus": {
                    "summary": "URL + дополнительный prompt и instructions",
                    "description": (
                        "Можно передать `source_url`/`video_url` ВМЕСТЕ с "
                        "`content` и `instructions` — сервис добавит контекст "
                        "из URL к вашему prompt."
                    ),
                    "value": {
                        "source_url": "https://en.wikipedia.org/wiki/Solar_System",
                        "content": "Make a presentation focused on planets habitability",
                        "instructions": "Highlight Mars and Europa, skip historical detail",
                        "n_slides": 7,
                        "language": "English",
                        "template": "modern",
                        "export_as": "pptx",
                    },
                },
            },
        )
        _set_json_response_example(
            generate_operation,
            "200",
            description="Презентация успешно создана.",
            example={
                "presentation_id": "d3000f96-096c-4768-b67b-e99aed029b57",
                "path": "/app_data/exports/d3000f96-096c-4768-b67b-e99aed029b57/Introduction_to_Machine_Learning.pptx",
                "edit_path": "/presentation?id=d3000f96-096c-4768-b67b-e99aed029b57",
            },
        )

    async_operation = _set_operation(
        openapi_schema,
        "/api/v1/ppt/presentation/generate/async",
        "post",
        summary="Поставить генерацию презентации в очередь",
        description=(
            "**Основной endpoint.** Запускает генерацию в фоне и сразу "
            "возвращает task id.\n\n"
            "Пример минимального body:\n\n"
            "```json\n"
            "{\n"
            "  \"content\": \"Create a presentation about ancient Rome\",\n"
            "  \"n_slides\": 7,\n"
            "  \"language\": \"Russian\",\n"
            "  \"export_as\": \"pptx\"\n"
            "}\n"
            "```"
        ),
        response_description="Задача фоновой генерации создана.",
    )
    if async_operation:
        _set_tags(async_operation, "1. Создание презентации")
        _set_error_examples(async_operation, include_insufficient_tokens=True)
        _set_json_request_examples(
            async_operation,
            {
                "async_prompt": {
                    "summary": "Асинхронная генерация по prompt",
                    "description": "Минимальный пример: тема + параметры.",
                    "value": {
                        "content": "Create a presentation about ancient Rome",
                        "slides_markdown": None,
                        "instructions": "Make it clear, visual, and useful.",
                        "tone": "professional",
                        "verbosity": "standard",
                        "web_search": False,
                        "n_slides": 7,
                        "language": "Russian",
                        "template": "general",
                        "include_table_of_contents": False,
                        "include_title_slide": True,
                        "files": None,
                        "video_url": None,
                        "source_url": None,
                        "export_as": "pptx",
                        "trigger_webhook": False,
                    },
                },
                "async_video_url": {
                    "summary": "Асинхронная генерация по видео-URL",
                    "description": (
                        "iOS-флоу: ссылка на mp4 + параметры → задача в очереди "
                        "→ polling /status/{id}. Время до готового PPTX: "
                        "~130–230 с для 10-минутного видео."
                    ),
                    "value": {
                        "video_url": "https://dn720706.ca.archive.org/0/items/ElephantsDream/ed_hd.mp4",
                        "n_slides": 7,
                        "language": "Russian",
                        "template": "general",
                        "export_as": "pptx",
                    },
                },
                "async_video_upload": {
                    "summary": "Асинхронная генерация по загруженному видео",
                    "description": (
                        "Шаг 1: POST /api/v1/ppt/files/upload (multipart, "
                        "поле `files`) → возвращает массив путей. "
                        "Шаг 2: путь(и) → в это поле `files`."
                    ),
                    "value": {
                        "files": ["/tmp/presenton/abc/recording.mp4"],
                        "n_slides": 7,
                        "language": "Russian",
                        "template": "general",
                        "export_as": "pptx",
                    },
                },
                "async_source_url": {
                    "summary": "Асинхронная генерация по веб-ссылке (Wikipedia)",
                    "description": (
                        "Сервис подтянет текст статьи и сделает по ней "
                        "презентацию. Время: ~30–90 с."
                    ),
                    "value": {
                        "source_url": "https://en.wikipedia.org/wiki/Machine_learning",
                        "n_slides": 7,
                        "language": "Russian",
                        "template": "general",
                        "export_as": "pptx",
                    },
                },
                "async_combined": {
                    "summary": "Комбинированный источник (URL + prompt)",
                    "description": (
                        "Можно сочетать поля: URL даёт контекст, `content` "
                        "и `instructions` уточняют фокус."
                    ),
                    "value": {
                        "source_url": "https://en.wikipedia.org/wiki/Photosynthesis",
                        "content": "Сделай презентацию для школьников 8-9 класса",
                        "instructions": "Простыми словами, минимум химических формул",
                        "n_slides": 6,
                        "language": "Russian",
                        "template": "general",
                        "export_as": "pptx",
                    },
                },
            },
        )
        _set_json_response_example(
            async_operation,
            "200",
            description="Задача создана.",
            example={
                "id": "task-9f1d8d5b7f0a4a8a9c7b6e1d2c3b4a5f",
                "status": "pending",
                "message": "Queued for generation",
                "error": None,
                "data": None,
            },
        )

    status_operation = _set_operation(
        openapi_schema,
        "/api/v1/ppt/presentation/status/{id}",
        "get",
        summary="Проверить статус фоновой генерации",
        description=(
            "**iOS polling endpoint.** Вызывайте после `/generate/async`.\n\n"
            "Интервал polling: 3-5 секунд.\n\n"
            "Возможные статусы:\n\n"
            "- `pending` - задача еще выполняется;\n"
            "- `completed` - презентация готова, в `data.path` лежит путь к файлу;\n"
            "- `error` - генерация завершилась ошибкой, смотрите поле `error`.\n\n"
            "Download URL:\n\n"
            "`https://appbackendnew.store` + `data.path`"
        ),
        response_description="Текущее состояние задачи.",
    )
    if status_operation:
        _set_tags(status_operation, "2. Проверка статуса")
        _set_error_examples(status_operation)
        _set_json_response_example(
            status_operation,
            "200",
            description="Статус задачи.",
            example={
                "id": "task-9f1d8d5b7f0a4a8a9c7b6e1d2c3b4a5f",
                "status": "completed",
                "message": "Presentation generation completed",
                "error": None,
                "data": {
                    "presentation_id": "d3000f96-096c-4768-b67b-e99aed029b57",
                    "path": "/app_data/exports/d3000f96-096c-4768-b67b-e99aed029b57/report.pptx",
                    "edit_path": "/presentation?id=d3000f96-096c-4768-b67b-e99aed029b57",
                },
            },
        )

    upload_operation = _set_operation(
        openapi_schema,
        "/api/v1/ppt/files/upload",
        "post",
        summary="Загрузить файлы-источники",
        description=(
            "Используйте его, если презентацию "
            "нужно создать по PDF/DOCX/TXT/изображениям.\n\n"
            "1. Загружайте файлы multipart form-data полем `files`.\n"
            "2. API возвращает массив временных путей.\n"
            "3. Эти пути нужно передать в поле `files` запроса `/generate/async`."
        ),
        response_description="Список путей загруженных файлов.",
    )
    if upload_operation:
        _set_tags(upload_operation, "4. Загрузка файлов")
        _set_error_examples(upload_operation)
        _set_json_response_example(
            upload_operation,
            "200",
            description="Файлы успешно загружены.",
            example=["/tmp/presenton/8f2b/source.pdf"],
        )

    image_generate_operation = _set_operation(
        openapi_schema,
        "/api/v1/ppt/images/generate",
        "get",
        summary="Сгенерировать изображение",
        description=(
            "Генерирует одно изображение по prompt. По умолчанию используется "
            "`gpt-image-1.5`; при rate limit сервис автоматически переключается "
            "на `dall-e-3`."
        ),
        response_description="Путь к изображению или URL stock-изображения.",
    )
    if image_generate_operation:
        _set_error_examples(image_generate_operation)
        _set_json_response_example(
            image_generate_operation,
            "200",
            description="Изображение создано.",
            example="/app_data/images/2f75f0a9-73c9-46d9-a916-d3c3fbc7d0a1.png",
        )

    image_search_operation = _set_operation(
        openapi_schema,
        "/api/v1/ppt/images/search",
        "get",
        summary="Найти stock-изображения",
        description=(
            "Ищет изображения через Pexels или Pixabay. Provider можно передать "
            "параметром `provider=pexels|pixabay`; если не передать, используется "
            "выбранный IMAGE_PROVIDER или Pexels по умолчанию."
        ),
        response_description="Список URL найденных изображений.",
    )
    if image_search_operation:
        _set_error_examples(image_search_operation)
        _set_json_response_example(
            image_search_operation,
            "200",
            description="Изображения найдены.",
            example=[
                "https://images.pexels.com/photos/3183150/pexels-photo-3183150.jpeg",
                "https://images.pexels.com/photos/3184465/pexels-photo-3184465.jpeg",
            ],
        )

    # ---------- Billing ----------

    me_operation = _set_operation(
        openapi_schema,
        "/api/v1/billing/me",
        "get",
        summary="Кошелёк текущего пользователя",
        description=(
            "Возвращает баланс токенов и состояние подписки. "
            "Если `X-User-Id` ранее не встречался — автоматически создаётся "
            "новый пользователь с `tokens=0` и `subscription=false`.\n\n"
            "**Заголовки**:\n\n"
            "- `X-API-Key: <SERVICE_API_KEY>` — обязателен.\n"
            "- `X-User-Id: <stable-uuid>` — обязателен. Значение должно быть "
            "стабильным для одного человека (`identifierForVendor` на iOS или "
            "собственный backend-side UUID).\n\n"
            "Поля ответа:\n\n"
            "- `tokens` — текущий баланс.\n"
            "- `subscription` — true, если последний Adapty-event был "
            "`subscription_started` или `subscription_renewed`.\n"
            "- `token_cost_per_generation` — сколько списывается за одну "
            "генерацию.\n"
            "- `subscription_tokens_grant` — сколько начисляется при покупке/"
            "продлении подписки."
        ),
        response_description="Кошелёк пользователя.",
    )
    if me_operation:
        _set_tags(me_operation, "6. Кошелёк пользователя")
        _set_error_examples(me_operation)
        _set_json_response_example(
            me_operation,
            "200",
            description="Баланс и состояние подписки.",
            example={
                "user_id": "user-ios-abc-123",
                "tokens": 99,
                "subscription": True,
                "subscription_expires_at": "2026-12-31T23:59:59",
                "token_cost_per_generation": 1,
                "subscription_tokens_grant": 100,
            },
        )

    credit_operation = _set_operation(
        openapi_schema,
        "/api/v1/billing/credit",
        "post",
        summary="Админ-операция: начислить токены пользователю",
        description=(
            "Только для оператора. Требует header `X-Admin-Key` со значением "
            "из env `ADMIN_API_KEY` (отдельный ключ от `SERVICE_API_KEY` — "
            "ротируется независимо).\n\n"
            "Каждое начисление добавляет запись `admin_credit` в "
            "`token_ledger_entries`, так что весь admin-фон полностью "
            "аудируется."
        ),
        response_description="Новый баланс пользователя.",
    )
    if credit_operation:
        _set_tags(credit_operation, "7. Админ-операции")
        _set_error_examples(credit_operation)
        _set_json_request_examples(
            credit_operation,
            {
                "credit_5": {
                    "summary": "Начислить 5 токенов",
                    "value": {
                        "user_id": "user-ios-abc-123",
                        "amount": 5,
                        "note": "promo for early adopter",
                    },
                },
            },
        )
        _set_json_response_example(
            credit_operation,
            "200",
            description="Токены начислены.",
            example={"user_id": "user-ios-abc-123", "balance": 5},
        )

    adapty_operation = _set_operation(
        openapi_schema,
        "/api/v1/billing/adapty/webhook",
        "post",
        summary="Adapty webhook receiver",
        description=(
            "Этот endpoint вызывает **Adapty**, не iOS-клиент.\n\n"
            "Заголовок `Adapty-Signature` обязателен. Подпись = "
            "HMAC-SHA256(raw_body, ADAPTY_WEBHOOK_SECRET) hex. Если подпись "
            "не совпадает — 401.\n\n"
            "Поддерживаются события:\n\n"
            "| `event_type` | Что делает |\n"
            "|---|---|\n"
            "| `subscription_started` | `subscription=true` + `+SUBSCRIPTION_TOKENS_GRANT` |\n"
            "| `subscription_renewed` | `+SUBSCRIPTION_TOKENS_GRANT` (флаг остаётся true) |\n"
            "| `subscription_cancelled` | `subscription=false`, токены не трогаем |\n"
            "| `subscription_expired` | `subscription=false`, токены не трогаем |\n\n"
            "Идемпотентность гарантируется на уровне `event_id` — повтор "
            "того же события не приводит к двойному начислению.\n\n"
            "Какие поля Adapty ожидаются в payload (упрощённо):\n\n"
            "```json\n"
            "{\n"
            "  \"event_id\": \"<uuid>\",\n"
            "  \"event_type\": \"subscription_started\",\n"
            "  \"profile\": {\n"
            "    \"customer_user_id\": \"user-ios-abc-123\",\n"
            "    \"profile_id\": \"adapty-profile-id\"\n"
            "  },\n"
            "  \"event_properties\": {\n"
            "    \"expires_at\": \"2026-12-31T23:59:59Z\"\n"
            "  }\n"
            "}\n"
            "```\n\n"
            "В iOS-приложении убедитесь, что `customer_user_id` в Adapty "
            "выставлен в **тот же** идентификатор, что вы шлёте в `X-User-Id`."
        ),
        response_description="Результат обработки события.",
    )
    if adapty_operation:
        _set_tags(adapty_operation, "8. Adapty webhook")
        adapty_responses = adapty_operation.setdefault("responses", {})
        adapty_responses["200"] = {
            "description": "Событие обработано (applied / duplicate / ignored).",
            "content": {
                "application/json": {
                    "examples": {
                        "applied": {
                            "summary": "Новое событие применено",
                            "value": {
                                "status": "applied",
                                "event_id": "evt-123",
                                "event_type": "subscription_started",
                                "subscription": True,
                                "tokens": 100,
                            },
                        },
                        "duplicate": {
                            "summary": "Тот же event_id уже обработан",
                            "value": {
                                "status": "duplicate",
                                "event_id": "evt-123",
                            },
                        },
                        "ignored": {
                            "summary": "Неизвестный event_type — игнорируем",
                            "value": {
                                "status": "ignored",
                                "event_type": "some_other_event",
                            },
                        },
                    }
                }
            },
        }
        adapty_responses["401"] = {
            "description": "Неверный/отсутствующий `Adapty-Signature`.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid Adapty signature."}
                }
            },
        }
        adapty_responses["400"] = {
            "description": "Кривой JSON или нет обязательных полей.",
            "content": {
                "application/json": {
                    "example": {"detail": "customer_user_id is required."}
                }
            },
        }

# Routers
app.include_router(API_V1_PPT_ROUTER)
app.include_router(API_V1_WEBHOOK_ROUTER)
app.include_router(API_V1_MOCK_ROUTER)
app.include_router(API_V1_AUTH_ROUTER)
app.include_router(BILLING_ROUTER)

# Mount app_data and static assets (direct FastAPI access; nginx also serves /static in Docker).
app_data_dir = get_app_data_directory_env()
if app_data_dir:
    os.makedirs(app_data_dir, exist_ok=True)
    app.mount("/app_data", StaticFiles(directory=app_data_dir), name="app_data")

static_dir = get_resource_path("static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Middlewares
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(UserConfigEnvUpdateMiddleware)
app.add_middleware(ServiceApiKeyMiddleware)
