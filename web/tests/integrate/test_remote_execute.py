"""
Интеграционные тесты для POST /cmd_center/remote_execute
Тестируют выполнение команд на удалённых нодах через микросервис
"""
import pytest
from web.tests.conftest import FakeAiohttpSession


class TestRemoteExecuteSuccess:
    """Тесты успешного выполнения команды на ноде"""
    
    @pytest.mark.asyncio
    async def test_execute_success(self, client, virtual_node_seed, pg_pool, flush_redis):
        """Успешное выполнение команды на ноде"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        node_id_1 = virtual_node_seed["node_id_1"]
        
        # Добавляем команду в whitelist (только base_command - первое слово)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
                "systemctl", True
            )
        
        # Мокируем успешный ответ от ноды
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={
                "success": True,
                "stdout": "nginx is running",
                "stderr": "",
                "exit_code": 0,
                "command": "systemctl status nginx"
            }
        )
        
        # Получаем данные ноды для запроса
        async with pg_pool.acquire() as conn:
            node_data = await conn.fetchrow(
                "SELECT n.private_ip, n.api_port FROM nodes n WHERE n.id = $1",
                node_id_1
            )
        
        response = await client.post(
            "/api/v1/cmd_center/remote_execute",
            json={
                "node_proto_id": vnode_id,
                "private_ip": str(node_data["private_ip"]),
                "api_port": node_data["api_port"],
                "cmd": "systemctl status nginx"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "nginx is running" in data["stdout"]
        assert data["stderr"] == ""
        
        # Проверяем что запись в истории создалась и обновилась
        async with pg_pool.acquire() as conn:
            history = await conn.fetchrow(
                "SELECT * FROM remote_execute_history WHERE command = $1",
                "systemctl status nginx"
            )
            assert history is not None
            assert history["status"] == 2  # ExecHistoryStatuses.success
            assert history["stdout"] == "nginx is running"
            assert history["exit_code"] == 0
            assert history["node_success"] is True
    
    @pytest.mark.asyncio
    async def test_execute_history_saved(self, client, virtual_node_seed, pg_pool, flush_redis):
        """Проверка что action_id сохраняется в remote_execute_history"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        node_id_1 = virtual_node_seed["node_id_1"]
        
        # Добавляем команду в whitelist (только base_command - первое слово)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
                "df", True
            )
        
        # Мокируем ответ
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={
                "success": True,
                "stdout": "Filesystem      Size  Used Avail Use%",
                "stderr": "",
                "exit_code": 0,
                "command": "df -h"
            }
        )
        
        # Получаем данные ноды
        async with pg_pool.acquire() as conn:
            node_data = await conn.fetchrow(
                "SELECT n.private_ip, n.api_port FROM nodes n WHERE n.id = $1",
                node_id_1
            )
        
        response = await client.post(
            "/api/v1/cmd_center/remote_execute",
            json={
                "node_proto_id": vnode_id,
                "private_ip": str(node_data["private_ip"]),
                "api_port": node_data["api_port"],
                "cmd": "df -h"
            }
        )
        
        assert response.status_code == 200
        
        # Проверяем что запись создалась в БД
        async with pg_pool.acquire() as conn:
            history_count = await conn.fetchval(
                "SELECT COUNT(*) FROM remote_execute_history WHERE command = $1",
                "df -h"
            )
            assert history_count == 1


class TestRemoteExecuteErrors:
    """Тесты ошибок при выполнении команды"""
    
    @pytest.mark.asyncio
    async def test_execute_not_whitelisted(self, client, virtual_node_seed, pg_pool, flush_redis):
        """Команда не в whitelist (400)"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        node_id_1 = virtual_node_seed["node_id_1"]
        
        # Добавляем другую команду в whitelist, чтобы активировать систему whitelist
        # но НЕ добавляем проверяемую команду nc - она должна быть заблокирована
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
                "ls", True
            )
        
        # Получаем данные ноды
        async with pg_pool.acquire() as conn:
            node_data = await conn.fetchrow(
                "SELECT n.private_ip, n.api_port FROM nodes n WHERE n.id = $1",
                node_id_1
            )
        
        response = await client.post(
            "/api/v1/cmd_center/remote_execute",
            json={
                "node_proto_id": vnode_id,
                "private_ip": str(node_data["private_ip"]),
                "api_port": node_data["api_port"],
                "cmd": "nc -l 1234"  # Команда не в whitelist
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["success"] is False
        assert "белого списка" in data["detail"]["message"]
        
        # Проверяем что история НЕ создалась
        async with pg_pool.acquire() as conn:
            history_count = await conn.fetchval(
                "SELECT COUNT(*) FROM remote_execute_history"
            )
            assert history_count == 0
    
    @pytest.mark.asyncio
    async def test_execute_node_unreachable(self, client, virtual_node_seed, pg_pool, flush_redis):
        """Нода не отвечает (ClientError) - история с failed_on_admin"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        node_id_1 = virtual_node_seed["node_id_1"]
        
        # Добавляем команду в whitelist (только base_command - первое слово)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
                "ps", True
            )
        
        # Мокируем ClientError (нода не отвечает)
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(raise_error=True)
        
        # Получаем данные ноды
        async with pg_pool.acquire() as conn:
            node_data = await conn.fetchrow(
                "SELECT n.private_ip, n.api_port FROM nodes n WHERE n.id = $1",
                node_id_1
            )
        
        response = await client.post(
            "/api/v1/cmd_center/remote_execute",
            json={
                "node_proto_id": vnode_id,
                "private_ip": str(node_data["private_ip"]),
                "api_port": node_data["api_port"],
                "cmd": "ps aux"
            }
        )
        
        assert response.status_code == 500
        data = response.json()
        assert "Ошибка исполнения на админке" in data["detail"]
        
        # Проверяем что история создалась со статусом failed_on_admin
        async with pg_pool.acquire() as conn:
            history = await conn.fetchrow(
                "SELECT * FROM remote_execute_history WHERE command = $1",
                "ps aux"
            )
            assert history is not None
            assert history["status"] == 4  # ExecHistoryStatuses.failed_on_admin
            assert history["status_code"] == 500
            assert history["exception_text"] is not None
    
    @pytest.mark.asyncio
    async def test_execute_node_error_response(self, client, virtual_node_seed, pg_pool, flush_redis):
        """Нода ответила с ошибкой (ClientResponseError) - история с failed_on_node"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        node_id_1 = virtual_node_seed["node_id_1"]
        
        # Добавляем команду в whitelist (только base_command - первое слово)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
                "ls", True
            )
        
        # Мокируем ответ с статусом 404 - raise_for_status() выбросит ClientResponseError
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={"error": "Not Found"},
            status=404
        )
        
        # Получаем данные ноды
        async with pg_pool.acquire() as conn:
            node_data = await conn.fetchrow(
                "SELECT n.private_ip, n.api_port FROM nodes n WHERE n.id = $1",
                node_id_1
            )
        
        response = await client.post(
            "/api/v1/cmd_center/remote_execute",
            json={
                "node_proto_id": vnode_id,
                "private_ip": str(node_data["private_ip"]),
                "api_port": node_data["api_port"],
                "cmd": "ls /nonexistent"
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["success"] is False
        assert "Ошибка исполнения на ноде" in data["detail"]["message"]
        
        # Проверяем что история создалась со статусом failed_on_node
        async with pg_pool.acquire() as conn:
            history = await conn.fetchrow(
                "SELECT * FROM remote_execute_history WHERE command = $1",
                "ls /nonexistent"
            )
            assert history is not None
            assert history["status"] == 3  # ExecHistoryStatuses.failed_on_node
            assert history["status_code"] == 404
            assert history["exception_text"] is not None


class TestRemoteExecuteHistoryUpdates:
    """Тесты обновления истории выполнения команд"""
    
    @pytest.mark.asyncio
    async def test_execute_history_updated_on_success(self, client, virtual_node_seed, pg_pool, flush_redis):
        """Обновление истории при успехе - проверка полей"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        node_id_1 = virtual_node_seed["node_id_1"]
        
        # Добавляем команду в whitelist (только base_command - первое слово)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
                "echo", True
            )
        
        # Мокируем успешный ответ с детальными данными
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(
            json_data={
                "success": True,
                "stdout": "test output line 1\ntest output line 2",
                "stderr": "warning: test",
                "exit_code": 0,
                "command": "echo test"
            }
        )
        
        # Получаем данные ноды
        async with pg_pool.acquire() as conn:
            node_data = await conn.fetchrow(
                "SELECT n.private_ip, n.api_port FROM nodes n WHERE n.id = $1",
                node_id_1
            )
        
        response = await client.post(
            "/api/v1/cmd_center/remote_execute",
            json={
                "node_proto_id": vnode_id,
                "private_ip": str(node_data["private_ip"]),
                "api_port": node_data["api_port"],
                "cmd": "echo test"
            }
        )
        
        assert response.status_code == 200
        
        # Детальная проверка полей в истории
        async with pg_pool.acquire() as conn:
            history = await conn.fetchrow(
                "SELECT * FROM remote_execute_history WHERE command = $1",
                "echo test"
            )
            assert history is not None
            assert history["status"] == 2  # success
            assert "test output line 1" in history["stdout"]
            assert "test output line 2" in history["stdout"]
            assert "warning: test" in history["stderr"]
            assert history["exit_code"] == 0
            assert history["status_code"] == 200
            assert history["node_success"] is True
            assert history["updated_at"] is not None
    
    @pytest.mark.asyncio
    async def test_execute_history_updated_on_error(self, client, virtual_node_seed, pg_pool, flush_redis):
        """Обновление истории при ошибке - проверка exception_text"""
        vnode_id = virtual_node_seed["vnode_id_1"]
        node_id_1 = virtual_node_seed["node_id_1"]
        
        # Добавляем команду в whitelist (только base_command - первое слово)
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO whitelist_commands (command, is_active) VALUES ($1, $2)",
                "cat", True
            )
        
        # Мокируем ошибку доступа
        client.app.state.cmd_center_aiohttp = FakeAiohttpSession(raise_error=True)
        
        # Получаем данные ноды
        async with pg_pool.acquire() as conn:
            node_data = await conn.fetchrow(
                "SELECT n.private_ip, n.api_port FROM nodes n WHERE n.id = $1",
                node_id_1
            )
        
        response = await client.post(
            "/api/v1/cmd_center/remote_execute",
            json={
                "node_proto_id": vnode_id,
                "private_ip": str(node_data["private_ip"]),
                "api_port": node_data["api_port"],
                "cmd": "cat /etc/shadow"
            }
        )
        
        assert response.status_code == 500
        
        # Проверяем exception_text в истории
        async with pg_pool.acquire() as conn:
            history = await conn.fetchrow(
                "SELECT * FROM remote_execute_history WHERE command = $1",
                "cat /etc/shadow"
            )
            assert history is not None
            assert history["status"] == 4  # failed_on_admin
            assert history["exception_text"] is not None
            assert "Simulated connection error" in history["exception_text"]
            assert history["updated_at"] is not None
