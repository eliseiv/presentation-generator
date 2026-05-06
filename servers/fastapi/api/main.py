import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from api.lifespan import app_lifespan
from api.middlewares import ServiceApiKeyMiddleware, UserConfigEnvUpdateMiddleware
from api.v1.auth.router import API_V1_AUTH_ROUTER
from api.v1.mock.router import API_V1_MOCK_ROUTER
from api.v1.ppt.router import API_V1_PPT_ROUTER
from api.v1.webhook.router import API_V1_WEBHOOK_ROUTER
from utils.get_env import get_app_data_directory_env
from utils.path_helpers import get_resource_path


OPENAPI_DESCRIPTION = """
Документация для интеграции iOS-приложения с backend сервиса Presenton.

В Swagger оставлены только endpoint-ы, которые нужны мобильному приложению:

1. создать задачу генерации презентации;
2. проверить статус генерации;
3. скачать готовый PPTX/PDF файл;
4. опционально загрузить файлы-источники;
5. опционально выполнить синхронную генерацию для тестов.

## Авторизация

Все API-запросы требуют сервисный API key из переменной окружения
`SERVICE_API_KEY`.

Передавайте ключ через кнопку **Authorize** в Swagger или заголовком:

```http
X-API-Key: <SERVICE_API_KEY>
```

## Рекомендуемый Flow Для iOS

1. `POST /api/v1/ppt/presentation/generate/async`
2. Сохранить `id` задачи из ответа.
3. Каждые 3-5 секунд вызывать `GET /api/v1/ppt/presentation/status/{id}`.
4. Когда `status=completed`, взять `data.path`.
5. Скачать файл по URL: `https://appbackendnew.store` + `data.path`.

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

Свободная строка с английским названием языка: `English`, `Russian`,
`Spanish`, `German`, `French`, `Chinese`, `Japanese`, `Arabic` и т. д.
Если не указано — определяется по содержимому `content`.

### `n_slides` — количество слайдов

Целое число от **1 до 50**. Если `include_table_of_contents=true`,
минимум **3**. Если не указано — модель сама подберёт количество.

### `instructions` — кастомизация

Произвольная строка с дополнительными инструкциями для LLM. Примеры:

- Имя автора: `"Use 'Александр Иванов' as the presenter name."`
- Фокус: `"Focus on practical examples for healthcare professionals."`
- Структура: `"Start with a problem statement, then 3 solutions, then ROI."`
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
]

IOS_OPENAPI_PATHS = {
    "/api/v1/ppt/presentation/generate/async": {"post"},
    "/api/v1/ppt/presentation/status/{id}": {"get"},
    "/api/v1/ppt/presentation/generate": {"post"},
    "/api/v1/ppt/files/upload": {"post"},
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
                "Для iOS скачивание выполняется обычным download-запросом с "
                "заголовком `X-API-Key`."
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


def _set_error_examples(operation: dict) -> None:
    responses = operation.setdefault("responses", {})
    responses["401"] = {
        "description": "API key не передан или неверный.",
        "content": {
            "application/json": {
                "example": {"detail": "Invalid or missing API key"}
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
            "**iOS:** используйте этот endpoint только для коротких тестов. "
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
        _set_error_examples(generate_operation)
        _set_json_request_examples(
            generate_operation,
            {
                "prompt": {
                    "summary": "Генерация из prompt",
                    "description": "Минимальный пример генерации PPTX из темы.",
                    "value": {
                        "content": "Introduction to Machine Learning",
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
            "  \"content\": \"Create a presentation about AI in healthcare\",\n"
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
        _set_error_examples(async_operation)
        _set_json_request_examples(
            async_operation,
            {
                "async_prompt": {
                    "summary": "Асинхронная генерация",
                    "description": "Пример:",
                    "value": {
                        "content": "Create a presentation about ancient Rome",
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
                        "export_as": "pptx",
                        "trigger_webhook": False,
                    },
                }
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
            "Когда `status=completed`, iOS должен собрать download URL:\n\n"
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
            "**Опциональный endpoint для iOS.** Используйте его, если презентацию "
            "нужно создать по PDF/DOCX/TXT/изображениям.\n\n"
            "1. iOS загружает файлы multipart form-data полем `files`.\n"
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

# Routers
app.include_router(API_V1_PPT_ROUTER)
app.include_router(API_V1_WEBHOOK_ROUTER)
app.include_router(API_V1_MOCK_ROUTER)
app.include_router(API_V1_AUTH_ROUTER)

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
