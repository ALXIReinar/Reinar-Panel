from pydantic import BaseModel, Field


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
    node_proto_id: int = Field(description='ID виртуальной ноды')
    metrics_port: int = Field(gt=0, le=65535, description='Порт для сбора статистики трафика ядра')
    command: str = Field(description='CLI команда для получения статистики трафика впн-ядра, сырых метрик')
    metrics_script: str | None = Field(None, description='Скрипт для получения метрик впн-ядра')
    core_lib: str | None = Field(None, description='Либы для скрипта получения метрик впн-ядра')
    metrics_parser_code: str = Field(description='Скрипт для обработки ответа с метриками впн-ядра. Нужен для преобразования в нужный формат')
    metrics_parser_libs: str | None = Field(description='Либы для работы parse_metrics_script')
