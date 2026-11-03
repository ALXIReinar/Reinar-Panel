from pydantic import BaseModel, ConfigDict, Field


class ConfigReadSchema(BaseModel):
    """Схема для чтения конфига"""

    model_config = ConfigDict(extra="ignore")

    node_proto_id: int = Field(description="ID виртуальной ноды")
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу")
    exclude_users: bool = Field(
        default=True,
        description="Вырезать ли список пользователей из конфига для экономии трафика",
    )


class ConfigWriteSchema(BaseModel):
    """Схема для записи конфига"""

    model_config = ConfigDict(extra="ignore")

    node_proto_id: int = Field(description="ID виртуальной ноды")
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу")
    content: str = Field(..., description="Новое содержимое файла")
    tmp_link: str = Field(..., description="Шаблон ссылки (proto_templates.url_tmp)")


class ConfigReadResponseSchema(BaseModel):
    """Схема ответа при чтении конфига"""

    success: bool
    content: str
    path: str


class ConfigWriteResponseSchema(BaseModel):
    """Схема ответа при записи конфига"""

    success: bool
    message: str
    path: str
    config_link: str
