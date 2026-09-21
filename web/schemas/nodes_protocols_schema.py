from pydantic import BaseModel, Field, field_validator
from pydantic_core.core_schema import ValidationInfo


class GetNodeProtoSchema(BaseModel):
    limit: int = Field(le=30)
    offset: int = Field(0, ge=0)


class UpdateNodeProtoSchema(BaseModel):
    """
    Схема для обновления виртуальной ноды

    - reload_core_command. Если пользователь оставляет значение без изменений, должно быть 0. NULL используется в качестве функционального значения, которое учитывается в обработках!
    """

    config_path: str | None = Field(None, min_length=1, description="Путь к конфигу протокола")
    title: str | None = Field(None, min_length=1, max_length=30, description="Название виртуальной ноды")
    metrics_port: int | None = Field(None, ge=1024, le=65535, description="Порт для сбора метрик трафика")
    proto_port: int | None = Field(None, ge=1024, le=65535, description="Порт протокола для клиентов")
    sub_node_address: str | None = Field(
        None, min_length=4, max_length=255, description="Домен протокола в конфиге клиентов"
    )
    user_visible: bool | None = Field(None, description="Видимость для пользователей")
    constant_node_data_obj: dict | None = Field(
        None,
        description='Джсон с любыми данными, которые нужны ноде. Доступен в суперобъекте пользователей в скриптах шаблонов',
    )
    reload_core_command: int | str | None = Field(
        0, description='Команда перезагрузки ядра(для обновления массива пользователей для подключения к ядру)'
    )

    @field_validator('reload_core_command', mode='before')
    @classmethod
    def reload_core_command_validate(cls, v):
        if isinstance(v, int) and v != 0:
            raise ValueError('reload_core_command не может быть числом')
        return v

    @field_validator('proto_port', mode='after')
    @classmethod
    def proto_port_validator(cls, v, info: ValidationInfo):
        if v is not None and info.data.get('metrics_port') is not None:
            if v == info.data['metrics_port']:
                raise ValueError('Порт протокола не может быть равен порту для сбора статистики трафика!')
        return v


class VNodeRegisterSchema(BaseModel):
    tmp_id: int = Field(description='Выступает как np.tmp_id. Protocols были вырезаны', alias='proto_id')
    node_id: int
    title: str  # Убрал max_length - контроль в валидаторе
    metrics_port: int | None = Field(None, le=65535, gt=0)
    proto_port: int = Field(le=65535, gt=0)
    config_path: str
    constant_node_data_obj: dict | None = Field(
        None, description='Входит в состав суперобъекта пользователей(в фарш для котлет нод клиента)'
    )

    sub_node_address: str | None = Field(
        None, description='Нода может прокинуть домен для подключения. Например, если использует tls слой шифрования'
    )
    metrics_command: str | None = Field(None, description='Команда сбора метрик индивидуально для этой Ноды')
    reload_core_command: str | None = Field(None, description='Команда перезагрузки ядра индивидуально для этой Ноды')

    @field_validator('title', mode='after')
    @classmethod
    def title_validator(cls, v):
        if len(v) <= 30:
            return v
        return f'{v[:27]}...'

    @field_validator('proto_port', mode='after')
    @classmethod
    def proto_port_validator(cls, v, info: ValidationInfo):
        metrics_port = info.data.get('metrics_port')
        if metrics_port is not None and metrics_port == v:
            raise ValueError('Metrics Port и Proto Port не могут быть равны')
        return v


class VNodeRegisterResultSchema(BaseModel):
    node_proto_id: int
    status: str | int = Field(description='Принимает: 2 - "success", 3 - "failed". Строки преобразует в int')
    title: str | None = None  # Убрал Field с max_length - контроль в валидаторе
    constant_node_data_obj: dict | None | int = Field(
        0, description='Входит в состав суперобъекта пользователей(в фарш для котлет нод клиента)'
    )
    reload_core_command: str | None = Field(None)
    metrics_command: str | None = Field(None)
    config_path: str | None = Field(None)
    service_name: str | None = Field(None)

    @field_validator('title', mode='after')
    @classmethod
    def title_validator(cls, v):
        if v is None:
            return v

        if len(v) <= 30:
            return v
        return f'{v[:27]}...'

    @field_validator('status', mode='after')
    @classmethod
    def status_validator(cls, v):
        status_map = {'success': 2, 'failed': 3}
        if isinstance(v, str) and (int_status := status_map.get(v.lower())):
            return int_status

        if v not in {1, 2, 3}:
            raise ValueError('Статус не может быть вне диапазона 1-3. 1 - "pending", 2 - "success", 3 - "failed"')

        return v
