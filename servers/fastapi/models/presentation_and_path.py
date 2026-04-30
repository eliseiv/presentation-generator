from pydantic import BaseModel, Field
import uuid


class PresentationAndPath(BaseModel):
    presentation_id: uuid.UUID = Field(
        description="ID созданной презентации.",
        examples=["d3000f96-096c-4768-b67b-e99aed029b57"],
    )
    path: str = Field(
        description="Путь к готовому PPTX/PDF файлу внутри app_data.",
        examples=[
            "/app_data/exports/d3000f96-096c-4768-b67b-e99aed029b57/Introduction_to_Machine_Learning.pptx"
        ],
    )


class PresentationPathAndEditPath(PresentationAndPath):
    edit_path: str = Field(
        description="Путь для открытия презентации в UI, если UI используется.",
        examples=["/presentation?id=d3000f96-096c-4768-b67b-e99aed029b57"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "presentation_id": "d3000f96-096c-4768-b67b-e99aed029b57",
                    "path": "/app_data/exports/d3000f96-096c-4768-b67b-e99aed029b57/Introduction_to_Machine_Learning.pptx",
                    "edit_path": "/presentation?id=d3000f96-096c-4768-b67b-e99aed029b57",
                }
            ]
        }
    }
