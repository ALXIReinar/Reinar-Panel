"""
Интеграционные тесты для PUT /cmd_center/config_file/write
Тестируют запись конфиг-файлов на удалённые ноды и генерацию подписочных ссылок
"""
import pytest
from unittest.mock import patch
from web.tests.conftest import FakeAiohttpSession


@pytest.fixture
async def vnode_with_template(db_pool, virtual_node_seed):
    """
    Виртуальная нода с настроенным шаблоном из БД (xray-vless-reality-tcp)
    Использует реальные шаблоны из seed_data вместо хардкода
    """
    vnode_id = virtual_node_seed["vnode_id_1"]
    
    async with db_pool.acquire() as conn:
        # 1. Устанавливаем config_path для виртуальной ноды
        await conn.execute(
            "UPDATE nodes_protocols SET config_path = $1 WHERE id = $2",
            "/etc/xray/config.json", vnode_id
        )
        
        # 2. Получаем реальный шаблон из БД (должен быть загружен через seed_data)
        template_id = await conn.fetchval(
            "SELECT id FROM proto_templates WHERE title = 'xray-vless-reality-tcp' AND is_accepted = true"
        )
        
        if not template_id:
            raise RuntimeError(
                "Шаблон 'xray-vless-reality-tcp' не найден в БД. "
                "Запустите: python -m web.db.seed_data"
            )
        
        # 3. Создаём или получаем протокол с этим шаблоном
        proto_id = await conn.fetchval(
            "SELECT id FROM protocols WHERE tmp_id = $1 LIMIT 1",
            template_id
        )
        
        if not proto_id:
            # Создаём протокол если его нет
            proto_id = await conn.fetchval(
                "INSERT INTO protocols (tmp_id, name) VALUES ($1, $2) RETURNING id",
                template_id, "Test VLESS Reality TCP"
            )
        
        # 4. Обновляем proto_id виртуальной ноды
        await conn.execute(
            "UPDATE nodes_protocols SET proto_id = $1 WHERE id = $2",
            proto_id, vnode_id
        )
    
    return vnode_id


class TestConfigFileWriteSuccess:
    """Тесты успешной записи конфиг-файла"""
    
    @pytest.mark.asyncio
    async def test_write_config_success(self, client, vnode_with_template, db_pool):
        """Успешная запись конфиг-файла и генерация ссылки"""
        vnode_id = vnode_with_template  # Фикстура уже возвращает int
        
        # Мокируем успешный ответ от ноды (запись файла)
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"success": True}
        )
        
        # Конфиг-файл для записи (используем реальный JSON из utils)
        import json
        with open("web/tests/utils/vless-tcp-server-metrics-copy.json", "r", encoding="utf-8") as f:
            config_content = json.dumps(json.load(f))
        
        response = await client.put(
            "/api/v1/private/cmd_center/config_file/write",
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
        
        # Проверяем что ссылка валидная (начинается с vless:// и содержит базовые параметры)
        link = data["sub_ready_link"]
        assert link.startswith("vless://")
        assert "encryption=none" in link
        assert "security=reality" in link
        # Проверяем что двойные плейсхолдеры подставились (не должно быть {{...}})
        assert "{{" not in link
    
    @pytest.mark.asyncio
    async def test_write_config_updates_config_link_in_db(self, client, vnode_with_template, db_pool):
        """Проверка что config_link обновляется в БД"""
        vnode_id = vnode_with_template
        
        # Мокируем успешный ответ от ноды
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"success": True}
        )
        
        # Используем реальный конфиг
        import json
        with open("web/tests/utils/vless-tcp-server-metrics-copy.json", "r", encoding="utf-8") as f:
            config_content = json.dumps(json.load(f))
        
        # Проверяем что config_link пустой ДО записи
        async with db_pool.acquire() as conn:
            old_link = await conn.fetchval(
                "SELECT config_link FROM nodes_protocols WHERE id = $1",
                vnode_id
            )
            assert old_link is None or old_link == ""
        
        response = await client.put(
            "/api/v1/private/cmd_center/config_file/write",
            json={
                "node_proto_id": vnode_id,
                "file_content": config_content,
                "flatten_json_users_key": None
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем что config_link обновился ПОСЛЕ записи
        async with db_pool.acquire() as conn:
            new_link = await conn.fetchval(
                "SELECT config_link FROM nodes_protocols WHERE id = $1",
                vnode_id
            )
            assert new_link is not None
            assert new_link != ""
            assert new_link.startswith("vless://")
            # Проверяем что это корректная ссылка без двойных плейсхолдеров
            assert "{{" not in new_link
    
    @pytest.mark.asyncio
    async def test_write_config_with_flatten_key(self, client, vnode_with_template, db_pool):
        """Запись конфиг-файла с параметром flatten_json_users_key"""
        vnode_id = vnode_with_template
        
        # Мокируем успешный ответ от ноды
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"success": True}
        )
        
        # Используем реальный конфиг с clients
        import json
        with open("web/tests/utils/vless-tcp-server-metrics-copy.json", "r", encoding="utf-8") as f:
            config_content = json.dumps(json.load(f))
        
        response = await client.put(
            "/api/v1/private/cmd_center/config_file/write",
            json={
                "node_proto_id": vnode_id,
                "file_content": config_content,
                "flatten_json_users_key": "inbounds.0.settings.clients"  # vless теперь на позиции 0
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
            "/api/v1/private/cmd_center/config_file/write",
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
    async def test_write_config_no_config_path(self, client, virtual_node_seed, db_pool):
        """config_path не указан (400)"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        
        # Убираем config_path (устанавливаем NULL)
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nodes_protocols SET config_path = NULL WHERE id = $1",
                vnode_id
            )
        
        response = await client.put(
            "/api/v1/private/cmd_center/config_file/write",
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
    async def test_write_config_node_error(self, client, vnode_with_template, db_pool):
        """Нода ответила с ошибкой - нет прав записи (400)"""
        vnode_id = vnode_with_template
        
        # Мокируем ответ с ошибкой 403 от ноды
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"error": "Permission denied"},
            status=403
        )
        
        response = await client.put(
            "/api/v1/private/cmd_center/config_file/write",
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
    async def test_write_config_node_unreachable(self, client, vnode_with_template, db_pool):
        """Нода недоступна - ClientError (400)"""
        vnode_id = vnode_with_template
        
        # Мокируем ClientError (нода не отвечает)
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(raise_error=True)
        
        response = await client.put(
            "/api/v1/private/cmd_center/config_file/write",
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
    async def test_write_config_link_generation_failed(self, client, vnode_with_template, db_pool):
        """Ошибка генерации ссылки - шаблон недоступен или некорректный (409)"""
        vnode_id = vnode_with_template
        
        # Мокируем успешную запись файла на ноду
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"success": True}
        )
        
        import json
        with open("web/tests/utils/vless-tcp-server-metrics-copy.json", "r", encoding="utf-8") as f:
            config_content = json.dumps(json.load(f))
        
        # Мокируем generate_link_from_json чтобы она вернула ошибку
        with patch('web.api.node_commander.node_commander_api.generate_link_from_json') as mock_generate:
            mock_generate.return_value = (False, "Url конфиг-ссылка не указана в шаблоне")
            
            response = await client.put(
                "/api/v1/private/cmd_center/config_file/write",
                json={
                    "node_proto_id": vnode_id,
                    "file_content": config_content,
                    "flatten_json_users_key": None
                }
            )
        
        assert response.status_code == 409
        data = response.json()
        detail = data.get("detail", data)  # FastAPI оборачивает в "detail"
        assert detail["success"] is False
        assert "Исключение при генерации ссылки по шаблону" in detail["message"]
        assert "Url конфиг-ссылка не указана" in detail["err_message"]


class TestConfigFileWriteValidation:
    """Тесты валидации параметров"""
    
    @pytest.mark.asyncio
    async def test_write_config_missing_node_proto_id(self, client):
        """Отсутствует обязательный параметр node_proto_id (422)"""
        response = await client.put(
            "/api/v1/private/cmd_center/config_file/write",
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
            "/api/v1/private/cmd_center/config_file/write",
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
