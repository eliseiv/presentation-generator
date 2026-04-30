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
Backend API сервиса Presenton для генерации и управления презентациями.

Основные сценарии:
- генерация презентаций из текста и файлов;
- загрузка и разбор документов;
- генерация, поиск, загрузка и удаление изображений;
- управление темами, шаблонами, шрифтами и слайдами;
- работа с чат-историей и webhook-подписками.

Все маршруты `/api/*` и защищенные ресурсы `/app_data/*` требуют сервисный
API key из переменной окружения `SERVICE_API_KEY`. Передавайте ключ в
заголовке `X-API-Key` или как `Authorization: Bearer <SERVICE_API_KEY>`.

Ключи LLM и image providers берутся из переменных окружения или из сохраненной
конфигурации приложения. Для OpenAI image generation используется
`OPENAI_API_KEY`; провайдер изображений по умолчанию - `gpt-image-1.5`, при
rate limit выполняется fallback на `dall-e-3`.
"""

OPENAPI_TAGS = [
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

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

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
