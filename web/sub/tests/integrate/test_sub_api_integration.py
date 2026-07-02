"""
Integration тесты для GET /sub/{b64_id} - выдача подписки для VPN-клиента.

GET /sub/{b64_id}:
1. Проверяет валидность подписки через get_sub_links()
2. Обрабатывает каждую config_link через executing_link_processing()
3. Формирует response с заголовками для VPN-клиента
4. Возвращает base64-encoded список ссылок

Критические SQL фильтры:
- ps.is_active = true (только активные подписки)
- u.is_deleted = false (только неудалённые пользователи)
- u.traffic_used_day_mb < sp.traffic_limit_day (в пределах лимита)
- ps.expire_date > now() (не истёкшие)
- np.user_visible = true (только видимые ноды)
"""
import pytest
import base64
import httpx
from fastapi import FastAPI

from web.sub.api.sub_api import router
from web.sub.api.sub_api import executing_link_processing


pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session")
def test_app():
    """
    FastAPI приложение для тестирования sub_api (создаётся один раз на сессию).
    """
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture(scope="function")
async def test_client(test_app, db_pool, sub_api_seed):
    """
    HTTP клиент для тестирования API (создаётся для каждого теста).
    
    Setup:
    1. Устанавливает db_pool в app.state.pg_pool
    2. Создаёт httpx.AsyncClient с ASGITransport
    
    Teardown:
    1. Закрывает AsyncClient (автоматически через context manager)
    2. Очищает state
    """
    try:
        # Setup: устанавливаем db_pool
        test_app.state.pg_pool = db_pool
        
        # Создаём HTTP клиент
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        # Teardown: очищаем state
        if hasattr(test_app.state, 'pg_pool'):
            delattr(test_app.state, 'pg_pool')


class TestGetSubEndpoint:
    """Integration тесты для GET /sub/{b64_id}"""
    
    async def test_get_sub_active_subscription(self, test_client, sub_api_seed):
        """
        Успешное получение подписки с активной подпиской.
        
        Проверяем:
        - Статус 200
        - Content-Type: text/plain
        - Response body в base64
        - Заголовки (Subscription-Userinfo, profile-title, etc.)
        - Ссылки содержат uuid пользователя
        """
        # Arrange
        b64_id = sub_api_seed['active_user']['b64_id']
        user_uuid = sub_api_seed['active_user']['uuid']
        
        # Act
        response = await test_client.get(f"/sub/{b64_id}")
        
        # Assert
        assert response.status_code == 200
        assert response.headers['content-type'] == 'text/plain; charset=utf-8'
        
        # Декодируем base64
        decoded = base64.b64decode(response.content).decode()
        
        # Проверяем что есть ссылки с UUID
        assert user_uuid in decoded
        assert "vless://" in decoded
        assert "test.server.com" in decoded
        
        # Проверяем заголовки
        assert 'subscription-userinfo' in response.headers
        assert 'profile-title' in response.headers
        assert 'profile-update-interval' in response.headers
        
        # Проверяем Subscription-Userinfo формат
        userinfo = response.headers['subscription-userinfo']
        assert 'download=' in userinfo
        assert 'total=' in userinfo
        assert 'expire=' in userinfo
    
    
    async def test_get_sub_inactive_subscription_limit_exceeded(self, test_client, sub_api_seed):
        """
        Подписка деактивирована из-за превышения лимита трафика.
        
        Проверяем:
        - Статус 200 (но с error messages)
        - Response содержит fake vless-ссылки с сообщениями об ошибках
        """
        import urllib.parse
        
        # Arrange
        b64_id = sub_api_seed['invalid_users']['limit_exceeded']['b64_id']
        
        # Act
        response = await test_client.get(f"/sub/{b64_id}")
        
        # Assert
        assert response.status_code == 200
        
        # Декодируем base64
        decoded = base64.b64decode(response.content).decode()
        
        # Проверяем что это error messages
        assert "00000000-0000-0000-0000-000000000000" in decoded
        assert "127.0.0.1" in decoded
        
        # Декодируем URL для проверки текста
        decoded_unquoted = urllib.parse.unquote(decoded)
        
        # Проверяем что есть сообщение о лимите или продлении
        assert ("лимит" in decoded_unquoted.lower() or "продл" in decoded_unquoted.lower())
    
    
    async def test_get_sub_inactive_subscription_expired(self, test_client, sub_api_seed):
        """Подписка истекла (expire_date < now())"""
        # Arrange
        b64_id = sub_api_seed['invalid_users']['expired']['b64_id']
        
        # Act
        response = await test_client.get(f"/sub/{b64_id}")
        
        # Assert
        assert response.status_code == 200
        
        decoded = base64.b64decode(response.content).decode()
        assert "00000000-0000-0000-0000-000000000000" in decoded
    
    
    async def test_get_sub_sql_filters_critical(self, test_client, sub_api_seed):
        """
        КРИТИЧЕСКИЙ ТЕСТ SQL ФИЛЬТРОВ: Проверяем что ссылки выдаются ТОЛЬКО валидным пользователям.
        
        Должны получить ссылки:
        - User A: активная подписка, в пределах лимита, не истёкшая ✅
        
        НЕ должны получить ссылки:
        - User B: превышен лимит трафика ❌
        - User C: подписка истекла ❌
        - User D: подписка неактивна ❌
        - User E: пользователь удалён ❌
        """
        # Act & Assert для каждого пользователя
        
        # User A - активный (должен получить ссылки)
        resp_a = await test_client.get(f"/sub/{sub_api_seed['active_user']['b64_id']}")
        decoded_a = base64.b64decode(resp_a.content).decode()
        assert sub_api_seed['active_user']['uuid'] in decoded_a
        assert "00000000-0000-0000-0000-000000000000" not in decoded_a  # НЕ error message
        
        # User B - превышен лимит (НЕ должен получить ссылки)
        resp_b = await test_client.get(f"/sub/{sub_api_seed['invalid_users']['limit_exceeded']['b64_id']}")
        decoded_b = base64.b64decode(resp_b.content).decode()
        assert "00000000-0000-0000-0000-000000000000" in decoded_b  # Error message
        
        # User C - истёкшая подписка (НЕ должен получить ссылки)
        resp_c = await test_client.get(f"/sub/{sub_api_seed['invalid_users']['expired']['b64_id']}")
        decoded_c = base64.b64decode(resp_c.content).decode()
        assert "00000000-0000-0000-0000-000000000000" in decoded_c
        
        # User D - неактивная подписка (НЕ должен получить ссылки)
        resp_d = await test_client.get(f"/sub/{sub_api_seed['invalid_users']['inactive']['b64_id']}")
        decoded_d = base64.b64decode(resp_d.content).decode()
        assert "00000000-0000-0000-0000-000000000000" in decoded_d
        
        # User E - удалённый пользователь (НЕ должен получить ссылки)
        resp_e = await test_client.get(f"/sub/{sub_api_seed['invalid_users']['deleted']['b64_id']}")
        decoded_e = base64.b64decode(resp_e.content).decode()
        assert "00000000-0000-0000-0000-000000000000" in decoded_e
    
    
    async def test_get_sub_response_headers(self, test_client, sub_api_seed):
        """
        Проверяем корректность заголовков ответа для VPN-клиента.
        
        Обязательные заголовки:
        - Subscription-Userinfo: upload=0; download={mb}; total={limit}; expire={timestamp}
        - profile-title: название подписки
        - profile-update-interval: интервал обновления
        - profile-web-page-url: ссылка на бот
        - announce: base64-encoded описание
        """
        # Arrange
        b64_id = sub_api_seed['active_user']['b64_id']
        
        # Act
        response = await test_client.get(f"/sub/{b64_id}")
        
        # Assert
        headers = response.headers
        
        # 1. Subscription-Userinfo
        assert 'subscription-userinfo' in headers
        userinfo = headers['subscription-userinfo']
        assert 'upload=0' in userinfo
        assert 'download=' in userinfo
        assert 'total=' in userinfo
        assert 'expire=' in userinfo
        
        # Проверяем формат чисел
        parts = userinfo.split('; ')
        for part in parts:
            key, value = part.split('=')
            assert value.isdigit(), f"{key} должен быть числом"
        
        # 2. profile-title
        assert 'profile-title' in headers
        assert len(headers['profile-title']) > 0
        
        # 3. profile-update-interval
        assert 'profile-update-interval' in headers
        assert headers['profile-update-interval'].isdigit()
        
        # 4. profile-web-page-url
        assert 'profile-web-page-url' in headers
        assert headers['profile-web-page-url'].startswith('http')
        
        # 5. announce (base64-encoded)
        assert 'announce' in headers
        announce = headers['announce']
        assert announce.startswith('base64:')
        # Декодируем announce
        announce_decoded = base64.b64decode(announce.split('base64:')[1]).decode()
        assert len(announce_decoded) > 0
    
    
    async def test_get_sub_multiple_locations(self, test_client, sub_api_seed, db_pool):
        """
        Проверяем что подписка содержит несколько локаций (config_link).
        
        Пользователь должен получить по одной ссылке на каждую видимую ноду.
        """
        # Arrange
        b64_id = sub_api_seed['active_user']['b64_id']
        
        # Получаем количество видимых нод для плана
        async with db_pool.acquire() as conn:
            nodes_count = await conn.fetchval("""
                SELECT COUNT(DISTINCT vsp.node_proto_id)
                FROM vnodes_sub_plans vsp
                JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
                WHERE vsp.sub_plan_id = $1
            """, sub_api_seed['plan_id'])
        
        # Act
        response = await test_client.get(f"/sub/{b64_id}")
        
        # Assert
        decoded = base64.b64decode(response.content).decode()
        links = [line for line in decoded.split('\n') if line.startswith('vless://')]
        
        # Должно быть столько же ссылок сколько видимых нод
        assert len(links) == nodes_count
        assert len(links) >= 2  # Минимум 2 ноды (vnode_id_10, vnode_id_11)
    
    
    async def test_get_sub_nonexistent_b64_id(self, test_client):
        """Запрос с несуществующим b64_id"""
        # Arrange
        fake_b64_id = "nonexistent-fake-id-12345"
        
        # Act
        response = await test_client.get(f"/sub/{fake_b64_id}")
        
        # Assert
        assert response.status_code == 200
        
        decoded = base64.b64decode(response.content).decode()
        # Должны получить error messages
        assert "00000000-0000-0000-0000-000000000000" in decoded


class TestExecutingLinkProcessingIntegration:
    """Integration тесты для executing_link_processing с реальными скриптами из БД"""
    
    async def test_with_real_script_from_db(self, sub_api_seed, db_pool):
        """
        Тест с реальным скриптом из БД.
        
        Проверяем что скрипт выполняется корректно и возвращает валидную ссылку.
        """
        # Arrange - получаем реальный скрипт из БД
        async with db_pool.acquire() as conn:
            script_data = await conn.fetchrow("""
                SELECT pt.sub_prepare_script, pt.sub_required_libs
                FROM proto_templates pt
                JOIN protocols p ON p.tmp_id = pt.id
                WHERE p.id = (
                    SELECT proto_id FROM nodes_protocols WHERE id = $1
                )
            """, sub_api_seed['vnode_id_10'])
        
        user_uuid = "test-uuid-real"
        config_link = "encryption=none&type=tcp"
        
        # Act
        success, result = await executing_link_processing(
            sub_prepare_script=script_data['sub_prepare_script'],
            required_libs=script_data['sub_required_libs'],
            user_uuid=user_uuid,
            config_link=config_link,
            user_id=1
        )
        
        # Assert
        assert success is True
        assert user_uuid in result
        assert config_link in result
        assert result.startswith("vless://")
    
    
    async def test_async_prepare_sub_from_db(self, sub_api_seed, db_pool):
        """
        Тест с асинхронным скриптом prepare_sub.
        
        Создаём временный async скрипт в БД и проверяем его исполнение.
        """
        # Arrange - обновляем скрипт на async версию
        async_script = '''
async def prepare_sub(user_uuid, config_link):
    """Асинхронная версия для тестов"""
    return f"vless://{user_uuid}@async.server.com:443?{config_link}#AsyncLocation"
'''
        
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE proto_templates
                SET sub_prepare_script = $1
                WHERE id = (
                    SELECT pt.id FROM proto_templates pt
                    JOIN protocols p ON p.tmp_id = pt.id
                    WHERE p.id = (
                        SELECT proto_id FROM nodes_protocols WHERE id = $2
                    )
                )
            """, async_script, sub_api_seed['vnode_id_10'])
            
            # Получаем обновлённый скрипт
            script_data = await conn.fetchrow("""
                SELECT sub_prepare_script, sub_required_libs
                FROM proto_templates
                WHERE id = (
                    SELECT pt.id FROM proto_templates pt
                    JOIN protocols p ON p.tmp_id = pt.id
                    WHERE p.id = (
                        SELECT proto_id FROM nodes_protocols WHERE id = $1
                    )
                )
            """, sub_api_seed['vnode_id_10'])
        
        user_uuid = "async-test-uuid"
        config_link = "type=ws&path=/api"
        
        # Act
        success, result = await executing_link_processing(
            sub_prepare_script=script_data['sub_prepare_script'],
            required_libs=script_data['sub_required_libs'],
            user_uuid=user_uuid,
            config_link=config_link,
            user_id=2
        )
        
        # Assert
        assert success is True
        assert user_uuid in result
        assert "async.server.com" in result
        assert "AsyncLocation" in result

