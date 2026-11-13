from pydantic import BaseModel, ConfigDict, Field


class ExecuteCommandSchema(BaseModel):
    """Схема для выполнения команды"""

    command: str = Field(..., min_length=1, description="Команда для выполнения")


class ExecuteResponseSchema(BaseModel):
    """Схема ответа после выполнения команды"""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    command: str


class MetricsSchema(BaseModel):
    """Схема запроса метрик виртуальной ноды"""

    model_config = ConfigDict(extra="ignore")

    node_proto_id: int = Field(description='ID виртуальной ноды')
    metrics_port: int = Field(gt=0, le=65535, description='Порт для сбора статистики трафика ядра')
