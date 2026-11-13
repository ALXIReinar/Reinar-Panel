from datetime import datetime  # noqa: F401, I001
from typing import Annotated
from pydantic import Field, BaseModel, IPvAnyAddress, field_validator

# По nodes.title нод-клиент находит себя (/startup, переменная NODE_TITLE): длина и набор символов —
# такие, чтобы имя без сюрпризов проходило в URL и в install.sh (буквы любых алфавитов, цифры, пробел, _ . -)
NODE_TITLE_PATTERN = r'^[\w .-]+$'


class NodeCreateSchema(BaseModel):
    """Схема для создания физической ноды"""

    ip: IPvAnyAddress = Field(description="Публичный IP адрес")
    private_ip: IPvAnyAddress = Field(description="Приватный IP адрес (WireGuard)")
    api_port: int = Field(..., gt=0, le=65535, description="Порт Node Client API")
    title: str = Field(..., min_length=1, max_length=64, pattern=NODE_TITLE_PATTERN, description="Название ноды")
    is_active: bool = Field(default=True, description="Активна ли нода")

    @field_validator('ip', 'private_ip', mode='after')
    @classmethod
    def ipvany2str(cls, v):
        return str(v)


class NodesGetSchema(BaseModel):
    is_active: bool | None = None
    limit: int = Field(le=50)
    offset: int = Field(0, ge=0)


class NodeUpdateSchema(BaseModel):
    """Схема для обновления физической ноды"""

    node_id: int = Field(description='ID физической ноды')
    ip: str | None = Field(None, description="Публичный IP адрес")
    private_ip: str | None = Field(None, description="Приватный IP адрес")
    api_port: int | None = Field(None, gt=0, le=65535, description="Порт Node Client API")
    title: str | None = Field(
        None, min_length=1, max_length=64, pattern=NODE_TITLE_PATTERN, description="Название ноды"
    )
    is_active: bool | None = Field(None, description="Активна ли нода")


class GetNodeProtoSchema(BaseModel):
    limit: int = Field(le=30)
    offset: int = Field(0, ge=0)


class StartupRequest(BaseModel):
    node_proto_ids: list[Annotated[int, Field(ge=1, le=2_147_483_647)]] = Field(
        default_factory=list, description="Пустой список = все зарегистрированные ноды"
    )


class NodeReinitSchema(BaseModel):
    """Реинициализация виртуальных нод физической ноды на её нод-клиенте"""

    node_proto_ids: list[Annotated[int, Field(ge=1, le=2_147_483_647)]] = Field(
        default_factory=list, description="ID виртуальных нод этой физической ноды; пустой список = все"
    )


class UserInjector(BaseModel):
    flatten_array_cursor: str
    extractor_script: str | None = None
    libs: str | None = None


class VnodeServiceData(BaseModel):
    node_proto_id: int
    filepath: str
    user_injectors: list[UserInjector]
    reload_command: str | None = None
    config2json_script: str | None = None
    json2config_script: str | None = None
    conf_converter_libs: str | None = None
    api_bulk_add_user_script: str | None = None
    api_bulk_delete_user_script: str | None = None
    metrics_command: str | None = None
    api_metrics_script: str | None = None
    proto_python_lib: str | None = None
    metrics_parser_code: str | None = None


class StartupResponse(BaseModel):
    node_title: str
    nodes: list[VnodeServiceData]
    missing: list[int]
