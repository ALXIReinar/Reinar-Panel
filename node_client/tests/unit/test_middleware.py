"""
Unit тесты для OnlyAdminAccessMiddleware

Стратегия:
- Тестируем middleware через mock ASGI app
- Проверяем корректную фильтрацию по IP адресу
- Проверяем что разрешённые IP пропускаются
- Проверяем что запрещённые IP получают 403 Forbidden
- Проверяем что non-HTTP connections пропускаются без проверки
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from node_client.api.middleware import OnlyAdminAccessMiddleware


# ========== Mock Helpers ==========

class MockASGIApp:
    """Mock для ASGI приложения"""
    def __init__(self):
        self.called = False
        self.scope = None
        self.receive = None
        self.send = None
    
    async def __call__(self, scope, receive, send):
        """Сохраняем вызов для проверки в тестах"""
        self.called = True
        self.scope = scope
        self.receive = receive
        self.send = send


def create_http_scope(client_ip: str | None) -> dict:
    """Создаёт HTTP scope с указанным client IP"""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/test",
        "headers": [],
    }
    
    if client_ip is not None:
        scope["client"] = (client_ip, 12345)  # (host, port)
    else:
        scope["client"] = None
    
    return scope


def create_websocket_scope(client_ip: str | None) -> dict:
    """Создаёт WebSocket scope"""
    scope = {
        "type": "websocket",
        "path": "/ws",
    }
    
    if client_ip is not None:
        scope["client"] = (client_ip, 12345)
    
    return scope


async def mock_receive():
    """Mock для receive callable"""
    return {"type": "http.request", "body": b""}


class MockSend:
    """Mock для send callable с отслеживанием вызовов"""
    def __init__(self):
        self.calls = []
    
    async def __call__(self, message):
        self.calls.append(message)


# ========== Тесты разрешённых IP ==========

@pytest.mark.asyncio
async def test_allows_localhost_127_0_0_1():
    """Middleware пропускает localhost (127.0.0.1)"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = create_http_scope("127.0.0.1")
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    # Проверяем что app был вызван (запрос прошёл)
    assert app.called is True
    assert app.scope == scope


@pytest.mark.asyncio
async def test_allows_internal_network_10_0_0_1():
    """Middleware пропускает внутренний IP 10.0.0.1"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = create_http_scope("10.0.0.1")
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    assert app.called is True
    assert app.scope == scope


@pytest.mark.asyncio
@patch('node_client.api.middleware.env')
async def test_allows_admin_panel_private_ip(mock_env):
    """Middleware пропускает IP админки из конфига"""
    # Настраиваем mock env
    mock_env.admin_panel_private_ip = "10.10.10.50"
    
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = create_http_scope("10.10.10.50")
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    assert app.called is True
    assert app.scope == scope


# ========== Тесты запрещённых IP ==========

@pytest.mark.asyncio
async def test_blocks_external_ip_8_8_8_8():
    """Middleware блокирует внешний IP (8.8.8.8)"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = create_http_scope("8.8.8.8")
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    # Проверяем что app НЕ был вызван
    assert app.called is False
    
    # Проверяем что был отправлен 403 Forbidden
    assert len(send.calls) > 0
    # Первый message должен быть http.response.start с статусом 403
    start_message = send.calls[0]
    assert start_message["type"] == "http.response.start"
    assert start_message["status"] == 403


@pytest.mark.asyncio
async def test_blocks_private_network_192_168():
    """Middleware блокирует приватные IP (192.168.x.x)"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = create_http_scope("192.168.1.100")
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    assert app.called is False
    
    # Проверяем 403
    start_message = send.calls[0]
    assert start_message["status"] == 403


@pytest.mark.asyncio
async def test_blocks_random_public_ip():
    """Middleware блокирует произвольный публичный IP"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = create_http_scope("203.0.113.42")  # TEST-NET-3
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    assert app.called is False
    
    start_message = send.calls[0]
    assert start_message["status"] == 403


# ========== Тесты edge cases ==========

@pytest.mark.asyncio
async def test_blocks_when_client_is_none():
    """Middleware блокирует запрос без client (client = None)"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = create_http_scope(None)
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    # Когда client = None, client_ip будет пустой строкой ''
    # Пустая строка НЕ входит в список разрешённых IP
    assert app.called is False
    
    start_message = send.calls[0]
    assert start_message["status"] == 403


@pytest.mark.asyncio
async def test_blocks_empty_string_ip():
    """Middleware блокирует пустой IP (edge case)"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    # Создаём scope с пустым client tuple
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/test",
        "headers": [],
        "client": ("", 12345),  # Пустой IP
    }
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    assert app.called is False
    
    start_message = send.calls[0]
    assert start_message["status"] == 403


# ========== Тесты non-HTTP connections ==========

@pytest.mark.asyncio
async def test_allows_websocket_without_ip_check():
    """Middleware пропускает WebSocket connections без проверки IP"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    # WebSocket с запрещённым IP должен пройти (проверка не выполняется)
    scope = create_websocket_scope("8.8.8.8")
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    # App должен быть вызван БЕЗ проверки IP
    assert app.called is True
    assert app.scope == scope


@pytest.mark.asyncio
async def test_allows_lifespan_events():
    """Middleware пропускает lifespan события (startup/shutdown)"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = {
        "type": "lifespan",
    }
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    # Lifespan события должны проходить без проверки
    assert app.called is True


# ========== Тесты корректности JSONResponse ==========

@pytest.mark.asyncio
async def test_forbidden_response_contains_content():
    """403 ответ содержит 'Forbidden' в теле"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = create_http_scope("8.8.8.8")
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    # Проверяем что отправлено 2 сообщения: start + body
    assert len(send.calls) >= 2
    
    # Второе сообщение должно быть http.response.body с телом ответа
    body_message = send.calls[1]
    assert body_message["type"] == "http.response.body"
    
    # Декодируем body (может быть JSON с "Forbidden")
    body = body_message.get("body", b"")
    assert b"Forbidden" in body or b"forbidden" in body.lower()


@pytest.mark.asyncio
async def test_forbidden_response_has_correct_headers():
    """403 ответ имеет корректные заголовки (Content-Type: application/json)"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    scope = create_http_scope("1.2.3.4")
    receive = mock_receive
    send = MockSend()
    
    await middleware(scope, receive, send)
    
    start_message = send.calls[0]
    headers = start_message.get("headers", [])
    
    # Проверяем что есть Content-Type заголовок
    content_type_found = False
    for name, value in headers:
        if name == b"content-type":
            assert b"application/json" in value
            content_type_found = True
            break
    
    assert content_type_found, "Content-Type header не найден в ответе"


# ========== Интеграционный тест ==========

@pytest.mark.asyncio
@patch('node_client.api.middleware.env')
async def test_middleware_integration_multiple_requests(mock_env):
    """Интеграционный тест: несколько запросов с разными IP"""
    mock_env.admin_panel_private_ip = "10.50.50.50"
    
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    # Сценарий 1: Разрешённый localhost
    scope1 = create_http_scope("127.0.0.1")
    await middleware(scope1, mock_receive, MockSend())
    assert app.called is True
    
    # Сброс состояния
    app.called = False
    
    # Сценарий 2: Разрешённый admin IP
    scope2 = create_http_scope("10.50.50.50")
    await middleware(scope2, mock_receive, MockSend())
    assert app.called is True
    
    # Сброс состояния
    app.called = False
    
    # Сценарий 3: Запрещённый внешний IP
    scope3 = create_http_scope("203.0.113.1")
    send3 = MockSend()
    await middleware(scope3, mock_receive, send3)
    assert app.called is False
    assert send3.calls[0]["status"] == 403
    
    # Сценарий 4: WebSocket (любой IP)
    app.called = False
    scope4 = create_websocket_scope("1.2.3.4")
    await middleware(scope4, mock_receive, MockSend())
    assert app.called is True


# ========== Тест на отсутствие побочных эффектов ==========

@pytest.mark.asyncio
async def test_middleware_does_not_modify_scope():
    """Middleware не модифицирует scope при пропускании запроса"""
    app = MockASGIApp()
    middleware = OnlyAdminAccessMiddleware(app)
    
    original_scope = create_http_scope("127.0.0.1")
    scope_copy = original_scope.copy()
    
    receive = mock_receive
    send = MockSend()
    
    await middleware(original_scope, receive, send)
    
    # Scope не должен быть изменён
    assert original_scope == scope_copy
