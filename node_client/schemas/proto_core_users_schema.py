from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BaseUserCoreSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node_proto_id: int = Field(..., gt=0, description='ID инстанса ядра (виртуальной ноды)')
    core_port: int | None = Field(None, gt=0, le=65535, description='Порт к апи ядра для взаимодействия через скрипты')
    custom_params: dict | None = Field(
        None, description='Зависимости для скрипта, которые идут отдельно от объекта пользователя'
    )
    users: list[dict] = Field(..., description='Список объектов пользователей')
    action: Literal["add", "delete"] = Field(description="Операция: 1/'add' - добавление, 2/'delete' - удаление")

    @field_validator("action", mode="before")
    @classmethod
    def convert_int_to_str(cls, value):
        mapping = {1: "add", 2: "delete"}
        return mapping.get(value, value)
