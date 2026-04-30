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


OPENAPI_TAGS = [
    {
        "name": "iOS Flow",
        "description": (
            "Минимальный набор endpoint-ов для iOS: создать async-задачу, "
            "проверить статус, скачать PPTX/PDF по `data.path`. "
            "Все запросы требуют `X-API-Key`."
        ),
    },
    {
        "name": "Auth",
        "description": "Настройка, проверка и завершение сессии администратора.",
    },
    {
        "name": "Presentation",
        "description": "Создание, генерация, экспорт, получение и редактирование презентаций.",
    },
    {
        "name": "Images",
        "description": "Поиск, генерация, загрузка и удаление изображений для презентаций.",
    },
    {"name": "Files", "description": "Загрузка и разбор файлов-источников."},
    {"name": "Slide", "description": "Редактирование отдельных слайдов."},
    {"name": "Chat", "description": "Диалоги и сообщения ассистента по презентации."},
    {"name": "Outlines", "description": "Потоковая генерация структуры презентации."},
    {"name": "Themes", "description": "Управление темами презентаций."},
    {"name": "V3 Theme", "description": "Генерация темы презентации."},
    {"name": "PPTX Slides", "description": "Импорт и обработка PPTX-слайдов."},
    {"name": "PPTX Fonts", "description": "Извлечение и обработка шрифтов из PPTX."},
    {"name": "PDF Slides", "description": "Импорт и обработка PDF-слайдов."},
    {"name": "OpenAI", "description": "Проверка доступных моделей OpenAI."},
    {"name": "Google", "description": "Проверка доступных моделей Google."},
    {"name": "Anthropic", "description": "Проверка доступных моделей Anthropic."},
    {"name": "Ollama", "description": "Список, статус и загрузка локальных моделей Ollama."},
    {"name": "Webhook", "description": "Подписка и отписка от webhook-событий."},
    {"name": "Mock", "description": "Тестовые маршруты для разработки."},
    {"name": "Icons", "description": "Поиск иконок для слайдов."},
    {"name": "fonts", "description": "Загрузка, список и удаление пользовательских шрифтов."},
    {"name": "slide-to-html", "description": "Преобразование слайдов в HTML."},
    {"name": "html-to-react", "description": "Преобразование HTML в React-компоненты."},
    {"name": "html-edit", "description": "Редактирование HTML-представления слайда."},
    {"name": "Layout Management", "description": "Управление пользовательскими layout-шаблонами."},
    {"name": "template-management", "description": "Управление шаблонами презентаций."},
]

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


def _add_ios_tag(operation: dict) -> None:
    tags = operation.setdefault("tags", [])
    if "iOS Flow" not in tags:
        operation["tags"] = ["iOS Flow", *tags]


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
        _add_ios_tag(generate_operation)
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
            "**Основной endpoint для iOS.** Запускает генерацию в фоне и сразу "
            "возвращает task id.\n\n"
            "Что делает iOS после ответа:\n\n"
            "1. Сохраняет `id` из ответа.\n"
            "2. Каждые 3-5 секунд вызывает "
            "`GET /api/v1/ppt/presentation/status/{id}`.\n"
            "3. При `status=completed` берет `data.path` и скачивает файл.\n\n"
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
        _add_ios_tag(async_operation)
        _set_error_examples(async_operation)
        _set_json_request_examples(
            async_operation,
            {
                "async_prompt": {
                    "summary": "Асинхронная генерация",
                    "description": "Рекомендуемый пример для iOS-приложения.",
                    "value": {
                        "content": "Create a presentation about AI in healthcare",
                        "instructions": "Make it clear, visual, and useful for mobile users.",
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
        _add_ios_tag(status_operation)
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
        _add_ios_tag(upload_operation)
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
