import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from node_client.api import main_router
from node_client.api.middleware import OnlyAdminAccessMiddleware
from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.config import env
from node_client.logger_config import log_event


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan для инициализации и остановки ConfigWriteBuffer
    
    Startup:
    - Создаём глобальный экземпляр ConfigWriteBuffer
    - Ноды регистрируются динамически при первом обращении
    
    Shutdown:
    - Останавливаем все воркеры
    - Сбрасываем остатки на диск
    """
    # ========== STARTUP ==========
    log_event("Запуск node-client...", level='INFO')
    
    # Инициализируем глобальный ConfigWriteBuffer
    app.state.core_buffer = ConfigWriteBuffer(max_batch=5, timeout=10.0)
    
    log_event("ConfigWriteBuffer инициализирован", level='INFO')
    log_event(f"Node-client запущен на порту {env.node_port}", level='INFO')
    
    yield
    
    # ========== SHUTDOWN ==========
    log_event("Остановка node-client...", level='INFO')
    
    # Останавливаем ConfigWriteBuffer
    await app.state.core_buffer.stop()
    
    log_event("Node-client остановлен", level='INFO')


app = FastAPI(default_response_class=ORJSONResponse, lifespan=lifespan)

app.include_router(main_router)
app.add_middleware(OnlyAdminAccessMiddleware)

if __name__ == '__main__':
    uvicorn.run('node_client.main:app', log_config=None, host="0.0.0.0", port=env.node_port, workers=env.uvicorn_workers)
