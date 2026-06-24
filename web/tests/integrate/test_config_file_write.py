"""
Интеграционные тесты для PUT /cmd_center/config_file/write
Тестируют запись конфиг-файлов на удалённые ноды и генерацию подписочных ссылок
"""
import pytest
from unittest.mock import patch
from web.tests.conftest import FakeAiohttpSession


@pytest.fixture
async def vnode_with_template(pg_pool, virtual_node_seed, proto_template_seed):
    """
    Виртуальная нода с настроенным шаблоном и spec параметрами
    """
    vnode_id = virtual_node_seed["vnode_id_1"]
    tmp_id = proto_template_seed["tmp_id"]
    
    async with pg_pool.acquire() as conn:
        # Устанавливаем config_path для виртуальной ноды
        await conn.execute(
            "UPDATE nodes_protocols SET config_path = $1 WHERE id = $2",
            "/etc/xray/config.json", vnode_id
        )
        
        # Устанавливаем url_tmp в proto_templates (шаблон ссылки)
        template_url = (
            "vless://{{user_uuid}}@{{node___address}}:{{inbounds___1___port}}?"
            "encryption=none&flow={{flow}}&security={{security}}&"
            "sni={{sni}}&fp={{fp}}&pbk={{pbk}}&sid={{sid}}&type={{network}}#{{node___title}}"
        )
        await conn.execute(
            "UPDATE proto_templates SET url_tmp = $1 WHERE id = $2",
            template_url, tmp_id
        )
        
        # Добавляем spec параметры для виртуальной ноды
        # Сначала создаём template_spec_params (без description - его нет в таблице)
        spec_params_data = [
            "flow",
            "security",
            "sni",
            "fp",
            "pbk",
            "sid",
            "network"
        ]
        
        for key in spec_params_data:
            spec_key_id = await conn.fetchval(
                "INSERT INTO template_spec_params (tmp_id, key) VALUES ($1, $2) RETURNING id",
                tmp_id, key
            )
            
            # Добавляем значения для виртуальной ноды
            value = {
                "flow": "xtls-rprx-vision",
                "security": "reality",
                "sni": "www.microsoft.com",
                "fp": "chrome",
                "pbk": "TEST_PUBLIC_KEY_ABC123",
                "sid": "709c400f8da05ef4",
                "network": "tcp"
            }[key]
            
            await conn.execute(
                """
                INSERT INTO nodes_protocoles_spec_params_values (node_proto_id, spec_key_id, value)
                VALUES ($1, $2, $3)
                """,
                vnode_id, spec_key_id, value
            )
    
    return vnode_id


class TestConfigFileWriteSuccess:
    """Тесты успешной записи конфиг-файла"""
    
    @pytest.mark.asyncio
    async def test_write_config_success(self, client, vnode_with_template, pg_pool):
        """Успешная запись конфиг-файла и генерация ссылки"""
        vnode_id = vnode_with_template  # Фикстура уже возвращает int
        
        # Мокируем успешный ответ от ноды (запись файла)
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"success": True}
        )
        
        # Конфиг-файл для записи
        config_content = '''
        {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {"port": 10085, "protocol": "dokodemo-door"},
                {"port": 443, "protocol": "vless"}
            ]
        }
        '''
        
        response = await client.put(
            "/api/v1/cmd_center/config_file/write",
            json={
                "node_proto_id": vnode_id,
                "file_content": config_content,
                "flatten_json_users_key": None
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "sub_ready_link" in data
        assert data["message"] == "Конфиг-файл ноды обновился, ссылка переопределена"
        assert "Перезагрузите ядро" in data["tip"]
        
        # Проверяем что ссылка содержит нужные параметры
        link = data["sub_ready_link"]
        assert link.startswith("vless://")
        assert "flow=xtls-rprx-vision" in link
        assert "security=reality" in link
        assert "pbk=TEST_PUBLIC_KEY_ABC123" in link
    
    @pytest.mark.asyncio
    async def test_write_config_updates_config_link_in_db(self, client, vnode_with_template, pg_pool):
        """Проверка что config_link обновляется в БД"""
        vnode_id = vnode_with_template
        
        # Мокируем успешный ответ от ноды
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"success": True}
        )
        
        config_content = '{"log": {"loglevel": "info"}, "inbounds": [{"port": 10085}, {"port": 443}]}'
        
        # Проверяем что config_link пустой ДО записи
        async with pg_pool.acquire() as conn:
            old_link = await conn.fetchval(
                "SELECT config_link FROM nodes_protocols WHERE id = $1",
                vnode_id
            )
            assert old_link is None or old_link == ""
        
        response = await client.put(
            "/api/v1/cmd_center/config_file/write",
            json={
                "node_proto_id": vnode_id,
                "file_content": config_content,
                "flatten_json_users_key": None
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем что config_link обновился ПОСЛЕ записи
        async with pg_pool.acquire() as conn:
            new_link = await conn.fetchval(
                "SELECT config_link FROM nodes_protocols WHERE id = $1",
                vnode_id
            )
            assert new_link is not None
            assert new_link.startswith("vless://")
            assert "pbk=TEST_PUBLIC_KEY_ABC123" in new_link
    
    @pytest.mark.asyncio
    async def test_write_config_with_flatten_key(self, client, vnode_with_template, pg_pool):
        """Запись конфиг-файла с параметром flatten_json_users_key"""
        vnode_id = vnode_with_template
        
        # Мокируем успешный ответ от ноды
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"success": True}
        )
        
        config_content = '''
        {
            "inbounds": [
                {"port": 10085},
                {
                    "port": 443,
                    "settings": {
                        "clients": [
                            {"id": "uuid1", "email": "user1"},
                            {"id": "uuid2", "email": "user2"}
                        ]
                    }
                }
            ]
        }
        '''
        
        response = await client.put(
            "/api/v1/cmd_center/config_file/write",
            json={
                "node_proto_id": vnode_id,
                "file_content": config_content,
                "flatten_json_users_key": "inbounds.1.settings.clients"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "sub_ready_link" in data


class TestConfigFileWriteErrors:
    """Тесты ошибочных сценариев при записи конфига"""
    
    @pytest.mark.asyncio
    async def test_write_config_vnode_not_found(self, client):
        """Виртуальная нода не существует (404)"""
        response = await client.put(
            "/api/v1/cmd_center/config_file/write",
            json={
                "node_proto_id": 99999,  # Несуществующая нода
                "file_content": '{"test": "config"}',
                "flatten_json_users_key": None
            }
        )
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не найдена" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_write_config_no_config_path(self, client, virtual_node_seed, pg_pool):
        """config_path не указан (400)"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        # Убираем config_path (устанавливаем NULL)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nodes_protocols SET config_path = NULL WHERE id = $1",
                vnode_id
            )
        
        response = await client.put(
            "/api/v1/cmd_center/config_file/write",
            json={
                "node_proto_id": vnode_id,
                "file_content": '{"test": "config"}',
                "flatten_json_users_key": None
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не указан" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_write_config_node_error(self, client, vnode_with_template, pg_pool):
        """Нода ответила с ошибкой - нет прав записи (400)"""
        vnode_id = vnode_with_template
        
        # Мокируем ответ с ошибкой 403 от ноды
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"error": "Permission denied"},
            status=403
        )
        
        response = await client.put(
            "/api/v1/cmd_center/config_file/write",
            json={
                "node_proto_id": vnode_id,
                "file_content": '{"test": "config"}',
                "flatten_json_users_key": None
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Ошибка исполнения на ноде" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_write_config_node_unreachable(self, client, vnode_with_template, pg_pool):
        """Нода недоступна - ClientError (400)"""
        vnode_id = vnode_with_template
        
        # Мокируем ClientError (нода не отвечает)
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(raise_error=True)
        
        response = await client.put(
            "/api/v1/cmd_center/config_file/write",
            json={
                "node_proto_id": vnode_id,
                "file_content": '{"test": "config"}',
                "flatten_json_users_key": None
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Ошибка исполнения на ноде" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_write_config_link_generation_failed(self, client, vnode_with_template, pg_pool):
        """Ошибка генерации ссылки - spec ключ отсутствует в шаблоне (409)"""
        vnode_id = vnode_with_template
        
        # Мокируем успешную запись файла на ноду
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"success": True}
        )
        
        # Мокируем generate_link_from_json чтобы она вернула ошибку
        with patch('web.api.node_commander.node_commander_api.generate_link_from_json') as mock_generate:
            mock_generate.return_value = (False, "Spec key: missing_key указан в кастомных параметрах, но отсутствует в ссылке-шаблоне")
            
            response = await client.put(
                "/api/v1/cmd_center/config_file/write",
                json={
                    "node_proto_id": vnode_id,
                    "file_content": '{"inbounds": [{"port": 10085}, {"port": 443}]}',
                    "flatten_json_users_key": None
                }
            )
        
        assert response.status_code == 409
        data = response.json()
        assert data["success"] is False
        assert "Исключение при генерации ссылки по шаблону" in data["message"]
        assert "missing_key" in data["err_message"]


class TestConfigFileWriteValidation:
    """Тесты валидации параметров"""
    
    @pytest.mark.asyncio
    async def test_write_config_missing_node_proto_id(self, client):
        """Отсутствует обязательный параметр node_proto_id (422)"""
        response = await client.put(
            "/api/v1/cmd_center/config_file/write",
            json={
                "file_content": '{"test": "config"}'
                # node_proto_id отсутствует
            }
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        # Проверяем что ошибка валидации связана с node_proto_id
        assert any("node_proto_id" in str(err) for err in data["detail"])
    
    @pytest.mark.asyncio
    async def test_write_config_missing_file_content(self, client):
        """Отсутствует обязательный параметр file_content (422)"""
        response = await client.put(
            "/api/v1/cmd_center/config_file/write",
            json={
                "node_proto_id": 1
                # file_content отсутствует
            }
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        # Проверяем что ошибка валидации связана с file_content
        assert any("file_content" in str(err) for err in data["detail"])
