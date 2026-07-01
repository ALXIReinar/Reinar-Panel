"""
Интеграционные тесты для GET /cmd_center/config_file/read
Тестируют чтение конфиг-файлов с удалённых нод
"""
import pytest
from web.tests.conftest import FakeAiohttpSession


class TestConfigFileReadSuccess:
    """Тесты успешного чтения конфиг-файла"""
    
    @pytest.mark.asyncio
    async def test_read_config_success(self, client, virtual_node_seed, db_pool):
        """Успешное чтение конфиг-файла с ноды"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        # Устанавливаем config_path для виртуальной ноды
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nodes_protocols SET config_path = $1 WHERE id = $2",
                "/etc/xray/config.json", vnode_id
            )
        
        # Мокируем успешный ответ от ноды с содержимым файла
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={
                "content": '{"log": {"loglevel": "warning"}, "inbounds": []}'
            }
        )
        
        response = await client.get(
            "/api/v1/cmd_center/config_file/read",
            params={
                "node_proto_id": vnode_id
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "file_content" in data
        assert "log" in data["file_content"]
        assert "inbounds" in data["file_content"]
        assert data["message"] == "Получен конфиг-файл от ноды"
    
    @pytest.mark.asyncio
    async def test_read_config_with_flatten_key(self, client, virtual_node_seed, db_pool):
        """Чтение конфиг-файла с параметром flatten_json_users_key"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        # Устанавливаем config_path
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nodes_protocols SET config_path = $1 WHERE id = $2",
                "/etc/v2ray/config.json", vnode_id
            )
        
        # Мокируем ответ с пользователями (которые должны быть вырезаны)
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={
                "content": '{"log": {"loglevel": "info"}, "clients": []}'
            }
        )
        
        response = await client.get(
            "/api/v1/cmd_center/config_file/read",
            params={
                "node_proto_id": vnode_id,
                "flatten_json_users_key": "inbounds.0.settings.clients"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "file_content" in data
        # Проверяем что список клиентов пустой (был вырезан на ноде)
        assert '"clients": []' in data["file_content"]


class TestConfigFileReadErrors:
    """Тесты ошибочных сценариев при чтении конфига"""
    
    @pytest.mark.asyncio
    async def test_read_config_vnode_not_found(self, client):
        """Виртуальная нода не существует (404)"""
        response = await client.get(
            "/api/v1/cmd_center/config_file/read",
            params={
                "node_proto_id": 99999  # Несуществующая нода
            }
        )
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не найдена" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_read_config_no_config_path(self, client, virtual_node_seed, db_pool):
        """config_path не указан (400)"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        # Убираем config_path (устанавливаем NULL)
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nodes_protocols SET config_path = NULL WHERE id = $1",
                vnode_id
            )
        
        response = await client.get(
            "/api/v1/cmd_center/config_file/read",
            params={
                "node_proto_id": vnode_id
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["success"] is False
        assert "не указан" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_read_config_node_error(self, client, virtual_node_seed, db_pool):
        """Нода ответила с ошибкой - файл не найден (400)"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        # Устанавливаем несуществующий путь
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nodes_protocols SET config_path = $1 WHERE id = $2",
                "/nonexistent/config.json", vnode_id
            )
        
        # Мокируем ответ с ошибкой 404 от ноды
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"error": "File not found"},
            status=404
        )
        
        response = await client.get(
            "/api/v1/cmd_center/config_file/read",
            params={
                "node_proto_id": vnode_id
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Ошибка исполнения на ноде" in data["detail"]["message"]
    
    @pytest.mark.asyncio
    async def test_read_config_node_unreachable(self, client, virtual_node_seed, db_pool):
        """Нода недоступна - ClientError (400)"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        # Устанавливаем config_path
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nodes_protocols SET config_path = $1 WHERE id = $2",
                "/etc/xray/config.json", vnode_id
            )
        
        # Мокируем ClientError (нода не отвечает)
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(raise_error=True)
        
        response = await client.get(
            "/api/v1/cmd_center/config_file/read",
            params={
                "node_proto_id": vnode_id
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Ошибка исполнения на ноде" in data["detail"]["message"]


class TestConfigFileReadValidation:
    """Тесты валидации параметров"""
    
    @pytest.mark.asyncio
    async def test_read_config_missing_node_proto_id(self, client):
        """Отсутствует обязательный параметр node_proto_id (422)"""
        response = await client.get(
            "/api/v1/cmd_center/config_file/read",
            params={}
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        # Проверяем что ошибка валидации связана с node_proto_id
        assert any("node_proto_id" in str(err) for err in data["detail"])
