from pydantic import BaseModel, Field


class ConfigReadSchema(BaseModel):
    """Схема для чтения конфига"""
    node_proto_id: int
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу")
    flatten_json_users_key: list[str] | None = Field(default=None, description="Ключ к списку пользователей в конфиге. При чтении с админки этот объект вырезается во избежание лишних сетевых расходов")
    config2json_script: str | None = Field(None, description='По умолчанию конвертация в JSON(Null значение)')
    json2config_script: str | None = Field(None, description='По умолчанию конвертация из JSON(Null значение)')
    conf_converter_libs: str | None = Field(None)

class ConfigWriteSchema(BaseModel):
    """Схема для записи конфига"""
    node_proto_id: int
    tmp_link: str
    path: str = Field(..., min_length=1, description="Путь к конфигурационному файлу")
    content: str = Field(..., description="Содержимое файла")
    flatten_json_users_key: list[str] | None = Field(default=None, description='Ключ к списку пользователей в конфиге. При записи этот объект переносится из старого файла')
    config2json_script: str | None = Field(None, description='По умолчанию конвертация в JSON(Null значение)')
    json2config_script: str | None = Field(None, description='По умолчанию конвертация из JSON(Null значение)')
    conf_converter_libs: str | None = Field(None)


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
