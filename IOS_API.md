# Presenton Backend API для iOS

Документ описывает минимальный набор endpoint-ов, которые нужны iOS-приложению для генерации презентаций через backend.

## Авторизация

Все API-запросы к `/api/*` требуют сервисный API key.

Передавайте ключ одним из способов:

```http
X-API-Key: <SERVICE_API_KEY>
```

или:

```http
Authorization: Bearer <SERVICE_API_KEY>
```

Рекомендуемый вариант для iOS:

```http
X-API-Key: <SERVICE_API_KEY>
```

## Основной Flow

Для iOS есть два сценария:

1. Синхронная генерация: проще, но запрос может выполняться долго.
2. Асинхронная генерация: рекомендуется для мобильного приложения.

Рекомендуемый production-flow:

```text
1. POST /api/v1/ppt/presentation/generate/async
2. GET  /api/v1/ppt/presentation/status/{task_id}
3. Скачать готовый файл по path из data
```

## 1. Асинхронно Создать Презентацию

Endpoint:

```http
POST /api/v1/ppt/presentation/generate/async
```

Headers:

```http
Content-Type: application/json
X-API-Key: <SERVICE_API_KEY>
```

Body:

```json
{
  "content": "Introduction to Machine Learning",
  "instructions": "Make it practical and suitable for executives.",
  "tone": "professional",
  "verbosity": "standard",
  "web_search": false,
  "n_slides": 5,
  "language": "English",
  "template": "general",
  "include_table_of_contents": false,
  "include_title_slide": true,
  "files": null,
  "export_as": "pptx",
  "trigger_webhook": false
}
```

Упрощенный body:

```json
{
  "content": "Create a presentation about AI in healthcare",
  "n_slides": 7,
  "language": "Russian",
  "export_as": "pptx"
}
```

Response:

```json
{
  "id": "task-9f1d8d5b7f0a4a8a9c7b6e1d2c3b4a5f",
  "status": "pending",
  "message": "Queued for generation",
  "error": null,
  "created_at": "2026-04-30T15:00:00.000000",
  "updated_at": "2026-04-30T15:00:00.000000",
  "data": null
}
```

Сохраните `id`. Он нужен для проверки статуса.

## 2. Проверить Статус Генерации

Endpoint:

```http
GET /api/v1/ppt/presentation/status/{task_id}
```

Headers:

```http
X-API-Key: <SERVICE_API_KEY>
```

Пример:

```http
GET /api/v1/ppt/presentation/status/task-9f1d8d5b7f0a4a8a9c7b6e1d2c3b4a5f
```

Возможные статусы:

```text
pending
completed
error
```

Response в процессе:

```json
{
  "id": "task-9f1d8d5b7f0a4a8a9c7b6e1d2c3b4a5f",
  "status": "pending",
  "message": "Generating slides",
  "error": null,
  "data": null
}
```

Response при успехе:

```json
{
  "id": "task-9f1d8d5b7f0a4a8a9c7b6e1d2c3b4a5f",
  "status": "completed",
  "message": "Presentation generation completed",
  "error": null,
  "data": {
    "presentation_id": "d3000f96-096c-4768-b67b-e99aed029b57",
    "path": "/app_data/exports/d3000f96-096c-4768-b67b-e99aed029b57/AI_in_healthcare.pptx",
    "edit_path": "/presentation?id=d3000f96-096c-4768-b67b-e99aed029b57"
  }
}
```

Response при ошибке:

```json
{
  "id": "task-9f1d8d5b7f0a4a8a9c7b6e1d2c3b4a5f",
  "status": "error",
  "message": "Presentation generation failed",
  "error": {
    "detail": "Presentation generation failed"
  },
  "data": null
}
```

## 3. Скачать Готовый Файл

В ответе `status=completed` поле:

```json
"path": "/app_data/exports/..."
```

Чтобы скачать файл, соберите полный URL:

```text
https://appbackendnew.store + path
```

Пример:

```text
https://appbackendnew.store/app_data/exports/d3000f96-096c-4768-b67b-e99aed029b57/AI_in_healthcare.pptx
```

Headers:

```http
X-API-Key: <SERVICE_API_KEY>
```

Файлы `/app_data/*` также защищены API key.

## Синхронная Генерация

Endpoint:

```http
POST /api/v1/ppt/presentation/generate
```

Использует тот же body, что async endpoint.

Response:

```json
{
  "presentation_id": "d3000f96-096c-4768-b67b-e99aed029b57",
  "path": "/app_data/exports/d3000f96-096c-4768-b67b-e99aed029b57/AI_in_healthcare.pptx",
  "edit_path": "/presentation?id=d3000f96-096c-4768-b67b-e99aed029b57"
}
```

Для iOS синхронный endpoint лучше использовать только для коротких презентаций или внутренних тестов, потому что генерация может занять долгое время.

## Параметры Генерации

| Поле | Тип | Обязательное | Описание |
|---|---|---:|---|
| `content` | string | да | Тема или исходный текст презентации. |
| `slides_markdown` | string[] или null | нет | Готовые Markdown-слайды вместо auto-outline. |
| `instructions` | string или null | нет | Дополнительные инструкции к стилю/структуре. |
| `tone` | string | нет | `default`, `casual`, `professional`, `funny`, `educational`, `sales_pitch`. |
| `verbosity` | string | нет | `concise`, `standard`, `text-heavy`. |
| `web_search` | boolean | нет | Web grounding, если поддерживается LLM. |
| `n_slides` | integer или null | нет | Количество слайдов. Если null, модель выберет сама. |
| `language` | string или null | нет | Язык презентации, например `Russian`, `English`. |
| `template` | string | нет | Шаблон, по умолчанию `general`. |
| `include_table_of_contents` | boolean | нет | Добавить содержание. |
| `include_title_slide` | boolean | нет | Добавить титульный слайд. |
| `files` | string[] или null | нет | Пути файлов после upload endpoint-а. |
| `export_as` | string | нет | `pptx` или `pdf`. |
| `trigger_webhook` | boolean | нет | Отправлять webhook-события. |

## Загрузка Файлов-Источников

Если презентацию нужно создать по PDF/DOCX/TXT/etc., сначала загрузите файлы.

Endpoint:

```http
POST /api/v1/ppt/files/upload
```

Headers:

```http
X-API-Key: <SERVICE_API_KEY>
Content-Type: multipart/form-data
```

Form field:

```text
files
```

Response:

```json
[
  "/tmp/presenton/8f2b/source.pdf"
]
```

Затем передайте эти пути в `files` при генерации:

```json
{
  "content": "Create a concise presentation from uploaded document",
  "files": ["/tmp/presenton/8f2b/source.pdf"],
  "n_slides": 8,
  "language": "Russian",
  "export_as": "pptx"
}
```

## Пример Swift: Async Генерация

```swift
import Foundation

struct GenerateRequest: Encodable {
    let content: String
    let n_slides: Int
    let language: String
    let export_as: String
}

struct TaskResponse: Decodable {
    let id: String
    let status: String
    let message: String?
}

func createPresentationTask() async throws -> TaskResponse {
    let url = URL(string: "https://appbackendnew.store/api/v1/ppt/presentation/generate/async")!
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("<SERVICE_API_KEY>", forHTTPHeaderField: "X-API-Key")

    let body = GenerateRequest(
        content: "Create a presentation about AI in healthcare",
        n_slides: 7,
        language: "Russian",
        export_as: "pptx"
    )
    request.httpBody = try JSONEncoder().encode(body)

    let (data, response) = try await URLSession.shared.data(for: request)
    guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
        throw URLError(.badServerResponse)
    }

    return try JSONDecoder().decode(TaskResponse.self, from: data)
}
```

## Пример Swift: Проверка Статуса

```swift
struct PresentationResult: Decodable {
    let presentation_id: String
    let path: String
    let edit_path: String
}

struct StatusResponse: Decodable {
    let id: String
    let status: String
    let message: String?
    let error: [String: String]?
    let data: PresentationResult?
}

func getTaskStatus(taskId: String) async throws -> StatusResponse {
    let url = URL(string: "https://appbackendnew.store/api/v1/ppt/presentation/status/\(taskId)")!
    var request = URLRequest(url: url)
    request.httpMethod = "GET"
    request.setValue("<SERVICE_API_KEY>", forHTTPHeaderField: "X-API-Key")

    let (data, response) = try await URLSession.shared.data(for: request)
    guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
        throw URLError(.badServerResponse)
    }

    return try JSONDecoder().decode(StatusResponse.self, from: data)
}
```

## Пример Swift: Скачать PPTX/PDF

```swift
func downloadPresentation(path: String) async throws -> URL {
    let fileURL = URL(string: "https://appbackendnew.store\(path)")!
    var request = URLRequest(url: fileURL)
    request.httpMethod = "GET"
    request.setValue("<SERVICE_API_KEY>", forHTTPHeaderField: "X-API-Key")

    let (tempURL, response) = try await URLSession.shared.download(for: request)
    guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
        throw URLError(.badServerResponse)
    }

    let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    let destination = documents.appendingPathComponent(fileURL.lastPathComponent)

    if FileManager.default.fileExists(atPath: destination.path) {
        try FileManager.default.removeItem(at: destination)
    }
    try FileManager.default.moveItem(at: tempURL, to: destination)
    return destination
}
```

## Хранение Файлов

Сгенерированные файлы хранятся на сервере в `app_data`.

TTL:

```text
2 часа
```

После TTL backend периодически удаляет старые презентации, картинки, uploads и exports. Поэтому iOS-приложение должно скачать результат сразу после `status=completed`.

## Ошибки

Частые коды:

```text
401 - нет X-API-Key или ключ неверный
500 - SERVICE_API_KEY не настроен на сервере или внутренняя ошибка генерации
404 - task id или презентация не найдены
422 - неверный JSON/body
```

Пример ошибки авторизации:

```json
{
  "detail": "Invalid or missing API key"
}
```