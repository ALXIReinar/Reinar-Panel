"""
Фикстуры для тестирования Telegram бота.

Использует:
- aiogram_tests для моков Message/CallbackQuery
- FakeAiohttpSession для имитации API запросов к SubService
- Настоящий Redis (в тестовом окружении)
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from redis.asyncio import Redis
from aiohttp import ClientSession

from bot.config_dir.config import env
from bot.core.api.aiohttp_conn import SubServiceConn


# ============================================================================
# Fake HTTP Client (по паттерну из web/sub/tests/conftest.py)
# ============================================================================

class FakeAiohttpResponse:
    """Имитация aiohttp.ClientResponse"""
    def __init__(self, json_data: dict, status: int = 200):
        self.json_data = json_data
        self.status = status
    
    async def json(self):
        return self.json_data
    
    async def text(self):
        import json
        return json.dumps(self.json_data)
    
    def raise_for_status(self):
        """Имитация raise_for_status - выбрасывает исключение для статусов >= 400"""
        if self.status >= 400:
            from aiohttp import ClientResponseError
            raise ClientResponseError(
                request_info=None,
                history=None,
                status=self.status,
                message=f'HTTP {self.status}'
            )
    
    def release(self):
        """Имитация release для освобождения соединения"""
        pass
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class FakeAiohttpContext:
    """Контекстный менеджер для async with"""
    def __init__(self, json_data: dict, status: int = 200):
        self.json_data = json_data
        self.status = status

    async def __aenter__(self):
        return FakeAiohttpResponse(self.json_data, self.status)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class FakeAiohttpSession:
    """
    Fake aiohttp.ClientSession для тестирования HTTP-запросов к SubService API.
    
    Поддерживает:
    - Spy-функционал (отслеживание вызовов)
    - Настройка status и json_data
    - Имитация ошибок
    """
    def __init__(self, json_data: dict | None = None, status: int = 200, raise_error: bool = False):
        self.json_data = {} if json_data is None else json_data
        self.status = status
        self.raise_error = raise_error
        
        # Spy attributes - для проверки что было вызвано
        self.post_calls = []
        self.delete_calls = []
        self.get_calls = []
        self.request_calls = []
    
    def request(self, method: str, url: str, *args, **kwargs):
        """Universal request method (используется в BaseAioHTTPClient)"""
        self.request_calls.append({
            'method': method,
            'url': url,
            'args': args,
            'kwargs': kwargs
        })
        
        if self.raise_error:
            from aiohttp import ClientError
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)

    def post(self, url: str, *args, **kwargs):
        """POST request spy"""
        self.post_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            from aiohttp import ClientError
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)

    def delete(self, url: str, *args, **kwargs):
        """DELETE request spy"""
        self.delete_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            from aiohttp import ClientError
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)

    def get(self, url: str, *args, **kwargs):
        """GET request spy"""
        self.get_calls.append({'url': url, 'args': args, 'kwargs': kwargs})
        
        if self.raise_error:
            from aiohttp import ClientError
            raise ClientError("Simulated connection error")
        
        return FakeAiohttpContext(self.json_data, self.status)
    
    async def close(self):
        """Имитация close"""
        pass


# ============================================================================
# Redis фикстуры (настоящий Redis для тестов)
# ============================================================================

@pytest_asyncio.fixture
async def redis_client():
    """
    Настоящий Redis клиент для тестов.
    После каждого теста очищает тестовые ключи по паттерну.
    """
    redis = Redis(
        host=getattr(env, 'redis_host'),
        port=getattr(env, 'redis_port'),
        password=env.redis_password if env.app_mode != 'local' else None,
        decode_responses=True
    )
    
    yield redis
    
    # Cleanup: удаляем все тестовые ключи (используем паттерн с app_mode и service_name)
    # Паттерн: {app_mode}:{service_name}:rate_limit:*
    pattern = f'{env.app_mode}:{env.service_name}:rate_limit:*'
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        if keys:
            await redis.delete(*keys)
        if cursor == 0:
            break
    
    await redis.aclose()


# ============================================================================
# API Client фикстуры
# ============================================================================

@pytest.fixture
def fake_http_session():
    """
    Фейковая HTTP сессия с дефолтными данными для успешных ответов.
    Можно переопределить в конкретных тестах.
    """
    default_user_data = {
        'id': 1,
        'tg_id': 123456789,
        'tg_username': 'test_user',
        'sub_count': 2,
        'registered_date': '2024-01-01T10:00:00'
    }
    
    return FakeAiohttpSession(json_data=default_user_data, status=200)


@pytest.fixture
def sub_service_conn(fake_http_session):
    """
    SubServiceConn с фейковой HTTP сессией.
    Можно использовать напрямую в хэндлерах.
    """
    return SubServiceConn(fake_http_session)


# ============================================================================
# Bot Mock фикстуры (для команд, которые шлют сообщения в админ канал)
# ============================================================================

@pytest.fixture
def mock_bot():
    """
    Мок объекта Bot для тестов, где бот сам отправляет сообщения.
    Например, on_startup() шлёт сообщение админу.
    """
    bot_mock = AsyncMock()
    bot_mock.send_message = AsyncMock(return_value=True)
    return bot_mock


# ============================================================================
# Утилиты для создания тестовых данных
# ============================================================================

@pytest.fixture
def sample_user_data():
    """Пример данных пользователя от SubService API"""
    return {
        'id': 1,
        'tg_id': 123456789,
        'tg_username': 'test_user',
        'sub_count': 2,
        'registered_date': '2024-01-01T10:00:00'
    }


@pytest.fixture
def sample_subscription_data():
    """Пример данных подписки пользователя"""
    return {
        'user_sub_id': 1,
        'sub_plan_id': 1,
        'is_active': True,
        'is_limited': False,
        'expire_date': '2025-01-01T10:00:00',
        'traffic_used_day_mb': 100,
        'infinite_traffic': False,
        'b64_id': 'test_b64_id',
        'infinite_expire': False,
        'traffic_limit_day': 10240,
        'used_mb': 5000,
        'used_mb_limit': 307200,
        'created_at': '2024-01-01T10:00:00',
        'title': 'Basic Plan',
        'offer_prices': [
            {
                'offer_id': 1,
                'cost': 49900,
                'ttl_days': 30,
                'traffic_day_limit': 10240,
                'traffic_limit': 307200,
                'infinite_expire': False,
                'infinite_traffic': False
            }
        ]
    }


# ============================================================================
# Комплексная фикстура для полного окружения хэндлера
# ============================================================================

@pytest_asyncio.fixture
async def handler_environment(redis_client, sub_service_conn):
    """
    Полное окружение для тестирования хэндлеров:
    - Настоящий Redis
    - Фейковый SubService API
    
    Возвращает словарь с зависимостями, которые хэндлеры ожидают.
    """
    return {
        'redis': redis_client,
        'aio_http': sub_service_conn
    }
