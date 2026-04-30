from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from enums.tone import Tone
from enums.verbosity import Verbosity


class GeneratePresentationRequest(BaseModel):
    content: str = Field(
        ...,
        description=(
            "Основной текст или тема, на основе которой будет создана презентация. "
            "Можно передать короткий prompt или развернутый материал."
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
        description="Дополнительные инструкции к стилю, структуре или содержанию.",
        examples=["Make it practical, concise, and suitable for executives."],
    )
    tone: Tone = Field(
        default=Tone.DEFAULT,
        description=(
            "Тон текста. Доступные значения: default, casual, professional, funny, "
            "educational, sales_pitch."
        ),
    )
    verbosity: Verbosity = Field(
        default=Verbosity.STANDARD,
        description="Плотность текста на слайдах: concise, standard или text-heavy.",
    )
    web_search: bool = Field(
        default=False,
        description="Включить web grounding, если выбранный LLM-провайдер это поддерживает.",
    )
    n_slides: Optional[int] = Field(
        default=None,
        description=(
            "Количество слайдов. Если не указано, модель сама подберет количество "
            "на основе входного материала."
        ),
        examples=[5],
    )
    language: Optional[str] = Field(
        default=None,
        description=(
            "Язык презентации. Если не указан, модель попытается определить язык "
            "автоматически."
        ),
        examples=["Russian"],
    )
    template: str = Field(
        default="general",
        description="Имя шаблона презентации. По умолчанию используется general.",
        examples=["general"],
    )
    include_table_of_contents: bool = Field(
        default=False,
        description="Добавить слайд с содержанием.",
    )
    include_title_slide: bool = Field(
        default=True,
        description="Добавить титульный слайд.",
    )
    files: Optional[List[str]] = Field(
        default=None,
        description=(
            "Пути файлов, ранее загруженных через /api/v1/ppt/files/upload. "
            "Сервис использует их как источник контента."
        ),
        examples=[["/tmp/presenton/abc/source.pdf"]],
    )
    export_as: Literal["pptx", "pdf"] = Field(
        default="pptx",
        description="Формат результата: pptx или pdf.",
        examples=["pptx"],
    )
    trigger_webhook: bool = Field(
        default=False,
        description="Отправить webhook-событие после завершения генерации.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
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
                }
            ]
        }
    }
