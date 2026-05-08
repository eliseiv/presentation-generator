from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from enums.tone import Tone
from enums.verbosity import Verbosity


class GeneratePresentationRequest(BaseModel):
    content: Optional[str] = Field(
        default=None,
        description=(
            "Основной текст или тема, на основе которой будет создана презентация. "
            "Можно передать короткий prompt или развернутый материал. "
            "Поле опциональное — но запрос должен содержать **минимум один** "
            "из источников: `content`, `slides_markdown`, `files`, "
            "`video_url`, `source_url`. Если вы передаёте только `video_url` "
            "или `source_url`, `content` можно не указывать — сервис сам "
            "сформирует тему."
        ),
        examples=["Introduction to Machine Learning"],
    )
    slides_markdown: Optional[List[str]] = Field(
        default=None,
        description=(
            "Готовая структура слайдов в Markdown. Если передана, сервис использует "
            "ее вместо автоматической генерации outline."
        ),
        examples=[
            [
                "# Machine Learning\n\nWhat it is and why it matters",
                "## Core Concepts\n\n- Data\n- Models\n- Training",
            ]
        ],
    )
    instructions: Optional[str] = Field(
        default=None,
        description=(
            "Дополнительные инструкции к стилю, структуре или содержанию. "
            "Используйте, если хотите задать имя автора, тематический фокус, "
            "ключевые термины и т. п."
        ),
        examples=["Make it practical, concise, and suitable for executives."],
    )
    tone: Tone = Field(
        default=Tone.DEFAULT,
        description=(
            "Тон текста на слайдах. Допустимые значения:\n"
            "- `default` — нейтральный универсальный тон.\n"
            "- `casual` — разговорный, дружественный.\n"
            "- `professional` — деловой, сдержанный (для executives, отчётов).\n"
            "- `funny` — лёгкий с юмором.\n"
            "- `educational` — обучающий, объясняющий шаг за шагом.\n"
            "- `sales_pitch` — продающий, акцент на выгодах."
        ),
        examples=["professional"],
    )
    verbosity: Verbosity = Field(
        default=Verbosity.STANDARD,
        description=(
            "Плотность текста на слайдах. Допустимые значения:\n"
            "- `concise` — минимум текста, тезисами.\n"
            "- `standard` — сбалансированный объём (по умолчанию).\n"
            "- `text-heavy` — развёрнутые описания, длинные параграфы."
        ),
        examples=["standard"],
    )
    web_search: bool = Field(
        default=False,
        description=(
            "Включить web grounding (поиск в интернете) на этапе генерации outline. "
            "Работает только если выбранный LLM-провайдер поддерживает grounding."
        ),
    )
    n_slides: Optional[int] = Field(
        default=None,
        description=(
            "Количество слайдов (1–50). Если не указано, модель сама подберёт "
            "количество на основе входного материала."
        ),
        examples=[5],
    )
    language: Optional[str] = Field(
        default=None,
        description=(
            "Язык презентации. Если не указан, язык определяется по содержимому "
            "поля `content`. Принимаются названия на английском: `English`, "
            "`Russian`, `Spanish`, `German`, `French`, `Chinese`, `Japanese`, "
            "`Arabic` и любые другие — модель распознаёт язык по имени."
        ),
        examples=["Russian"],
    )
    template: Literal["general", "modern", "standard", "swift"] = Field(
        default="general",
        description=(
            "Шаблон оформления презентации. Допустимые значения:\n"
            "- `general` — универсальный набор слайдов (intro, bullets, metrics, "
            "table, team, quote и т. п.). По умолчанию.\n"
            "- `modern` — современный pitch-deck стиль (intro pitch, image+text, "
            "metrics, charts).\n"
            "- `standard` — деловой, классический (header+counter, splits, "
            "team cards, visual metrics).\n"
            "- `swift` — компактный, тезисный (intro, simple bullets, timeline, "
            "metrics numbers)."
        ),
        examples=["general"],
    )
    include_table_of_contents: bool = Field(
        default=False,
        description=(
            "Добавить слайд с содержанием. Требует `n_slides` >= 3."
        ),
    )
    include_title_slide: bool = Field(
        default=True,
        description="Добавить титульный слайд (intro) первым.",
    )
    files: Optional[List[str]] = Field(
        default=None,
        description=(
            "Пути файлов, ранее загруженных через `POST /api/v1/ppt/files/upload`. "
            "Сервис использует их как источник контента (PDF/DOCX/TXT/изображения, "
            "видео `.mp4/.mov/.mkv/.webm` и аудио `.mp3/.wav/.m4a` — для видео и "
            "аудио сервис извлекает речь через Whisper и описывает кадры через "
            "GPT-4o Vision)."
        ),
        examples=[["/tmp/presenton/abc/source.pdf"]],
    )
    video_url: Optional[str] = Field(
        default=None,
        description=(
            "Прямая ссылка на видео-файл (например `https://.../video.mp4`). "
            "Сервис извлекает аудио через ffmpeg, транскрибирует его через "
            "Whisper, плюс семплирует один кадр в 10 секунд и описывает их "
            "через GPT-4o Vision. Полученный контекст используется как основа "
            "для генерации слайдов. Лимит длительности — 30 минут."
        ),
        examples=[
            "https://dn720706.ca.archive.org/0/items/ElephantsDream/ed_hd.mp4"
        ],
    )
    source_url: Optional[str] = Field(
        default=None,
        description=(
            "Ссылка на текстовую веб-страницу (например статью Wikipedia). "
            "Сервис скачивает HTML, извлекает чистый текст (через REST API "
            "Wikipedia или trafilatura для других сайтов) и использует его "
            "как контекст для генерации презентации."
        ),
        examples=[
            "https://en.wikipedia.org/wiki/Machine_learning"
        ],
    )
    export_as: Literal["pptx", "pdf"] = Field(
        default="pptx",
        description=(
            "Формат результата:\n"
            "- `pptx` — PowerPoint (редактируемый, с реальными слайдами).\n"
            "- `pdf` — PDF (для распространения, не редактируется)."
        ),
        examples=["pptx"],
    )
    trigger_webhook: bool = Field(
        default=False,
        description=(
            "Отправить webhook-событие после завершения генерации "
            "(`presentation_generation_completed` или `presentation_generation_failed`). "
            "Получатели настраиваются через webhook subscription endpoints."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
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
                }
            ]
        }
    }
