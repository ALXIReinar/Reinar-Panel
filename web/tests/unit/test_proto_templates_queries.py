"""
Unit тесты для ProtoTemplatesQueries (web/data/sql_queries/proto_templates_sql.py).
Тестирует SQL queries на уровне репозитория (без API слоя).
"""

import pytest

from web.data.sql_queries.proto_templates_sql import ProtoTemplatesQueries

# ==================== UPDATE with cli_cmds (Задача 2.1) ====================


@pytest.mark.asyncio
async def test_update_cli_cmds_success(db_pool):
    """Успешное обновление cli_cmds с списком команд"""
    async with db_pool.acquire() as conn:
        # Используем существующий системный шаблон (первый xray-*)
        tmp_id_row = await conn.fetchrow("SELECT id FROM proto_templates WHERE title ILIKE 'xray-%' LIMIT 1")
        tmp_id = tmp_id_row["id"]

        # Обновляем cli_cmds
        queries = ProtoTemplatesQueries(conn)
        commands = ["command1", "command2", "command3"]
        status_code, message = await queries.update(
            tmp_id=tmp_id,
            title=None,
            url_tmp=None,
            required_user_data_obj=None,
            constant_user_data_obj=None,
            proto_python_lib=None,
            sub_prepare_script=None,
            sub_required_libs=None,
            api_bulk_delete_user_script=None,
            api_bulk_add_user_script=None,
            metrics_parser_code=None,
            metrics_command=None,
            bulk_delete_script_custom_params=None,
            bulk_add_script_custom_params=None,
            api_metrics_script=None,
            json2config_script=None,
            config2json_script=None,
            conf_converter_libs=None,
            cli_cmds=commands,
        )

        assert status_code == 200
        assert message == "Шаблон обновлён"

        # Проверяем что cli_cmds сохранены в БД
        result = await conn.fetchval("SELECT cli_cmds FROM proto_templates WHERE id = $1", tmp_id)
        assert result is not None
        assert "commands" in result
        assert result["commands"] == commands


@pytest.mark.asyncio
async def test_update_cli_cmds_wraps_in_commands_dict(db_pool):
    """Проверка что cli_cmds сохраняется в формате {"commands": [...]}"""
    async with db_pool.acquire() as conn:
        # Используем существующий системный шаблон
        tmp_id_row = await conn.fetchrow("SELECT id FROM proto_templates WHERE title ILIKE 'singbox-%' LIMIT 1")
        tmp_id = tmp_id_row["id"]

        # Обновляем cli_cmds
        queries = ProtoTemplatesQueries(conn)
        commands = ["cmd_a", "cmd_b"]
        await queries.update(
            tmp_id=tmp_id,
            title=None,
            url_tmp=None,
            required_user_data_obj=None,
            constant_user_data_obj=None,
            proto_python_lib=None,
            sub_prepare_script=None,
            sub_required_libs=None,
            api_bulk_delete_user_script=None,
            api_bulk_add_user_script=None,
            metrics_parser_code=None,
            metrics_command=None,
            bulk_delete_script_custom_params=None,
            bulk_add_script_custom_params=None,
            api_metrics_script=None,
            json2config_script=None,
            config2json_script=None,
            conf_converter_libs=None,
            cli_cmds=commands,
        )

        # Проверяем точный формат сохранения
        result = await conn.fetchval("SELECT cli_cmds FROM proto_templates WHERE id = $1", tmp_id)
        # Должно быть {"commands": ["cmd_a", "cmd_b"]}
        assert isinstance(result, dict)
        assert list(result.keys()) == ["commands"]
        assert result["commands"] == ["cmd_a", "cmd_b"]


@pytest.mark.asyncio
async def test_update_cli_cmds_template_not_found(db_pool):
    """Обновление cli_cmds несуществующего шаблона возвращает 404"""
    async with db_pool.acquire() as conn:
        queries = ProtoTemplatesQueries(conn)
        status_code, message = await queries.update(
            tmp_id=999999,  # Несуществующий ID
            title=None,
            url_tmp=None,
            required_user_data_obj=None,
            constant_user_data_obj=None,
            proto_python_lib=None,
            sub_prepare_script=None,
            sub_required_libs=None,
            api_bulk_delete_user_script=None,
            api_bulk_add_user_script=None,
            metrics_parser_code=None,
            metrics_command=None,
            bulk_delete_script_custom_params=None,
            bulk_add_script_custom_params=None,
            api_metrics_script=None,
            json2config_script=None,
            config2json_script=None,
            conf_converter_libs=None,
            cli_cmds=["test_command"],
        )

        assert status_code == 404
        assert message == "Шаблон не найден"


@pytest.mark.asyncio
async def test_update_cli_cmds_with_empty_list_clears_field(db_pool):
    """Передача пустого списка cli_cmds очищает команды ({"commands": []})"""
    async with db_pool.acquire() as conn:
        # Создаём тестовый шаблон с командами
        tmp_id = await conn.fetchval(
            """
            INSERT INTO proto_templates (title, cli_cmds) 
            VALUES ($1, $2) 
            RETURNING id
            """,
            "test-ClearCommands",
            {"commands": ["old_cmd_1", "old_cmd_2"]},
        )

        # Обновляем cli_cmds пустым списком
        queries = ProtoTemplatesQueries(conn)
        status_code, message = await queries.update(
            tmp_id=tmp_id,
            title=None,
            url_tmp=None,
            required_user_data_obj=None,
            constant_user_data_obj=None,
            proto_python_lib=None,
            sub_prepare_script=None,
            sub_required_libs=None,
            api_bulk_delete_user_script=None,
            api_bulk_add_user_script=None,
            metrics_parser_code=None,
            metrics_command=None,
            bulk_delete_script_custom_params=None,
            bulk_add_script_custom_params=None,
            api_metrics_script=None,
            json2config_script=None,
            config2json_script=None,
            conf_converter_libs=None,
            cli_cmds=[],  # Пустой список
        )

        assert status_code == 200
        assert message == "Шаблон обновлён"

        # Проверяем что команды очищены
        result = await conn.fetchval("SELECT cli_cmds FROM proto_templates WHERE id = $1", tmp_id)
        assert result == {"commands": []}


@pytest.mark.asyncio
async def test_update_cli_cmds_with_none_skips_update(db_pool):
    """Передача cli_cmds=None пропускает обновление поля"""
    async with db_pool.acquire() as conn:
        # Создаём тестовый шаблон с командами
        original_commands = {"commands": ["original_cmd"]}
        tmp_id = await conn.fetchval(
            """
            INSERT INTO proto_templates (title, cli_cmds) 
            VALUES ($1, $2) 
            RETURNING id
            """,
            "test-SkipUpdate",
            original_commands,
        )

        # Обновляем другие поля, но cli_cmds=None
        queries = ProtoTemplatesQueries(conn)
        status_code, message = await queries.update(
            tmp_id=tmp_id,
            title="test-SkipUpdate-Updated",  # Обновляем title
            url_tmp=None,
            required_user_data_obj=None,
            constant_user_data_obj=None,
            proto_python_lib=None,
            sub_prepare_script=None,
            sub_required_libs=None,
            api_bulk_delete_user_script=None,
            api_bulk_add_user_script=None,
            metrics_parser_code=None,
            metrics_command=None,
            bulk_delete_script_custom_params=None,
            bulk_add_script_custom_params=None,
            api_metrics_script=None,
            json2config_script=None,
            config2json_script=None,
            conf_converter_libs=None,
            cli_cmds=None,  # Пропускаем обновление
        )

        assert status_code == 200
        assert message == "Шаблон обновлён"

        # Проверяем что cli_cmds НЕ изменились
        result = await conn.fetchval("SELECT cli_cmds FROM proto_templates WHERE id = $1", tmp_id)
        assert result == original_commands


# ==================== DELETE (Задача 2.3) ====================


@pytest.mark.asyncio
async def test_delete_success(db_pool):
    """Успешное удаление шаблона без связанных записей"""
    async with db_pool.acquire() as conn:
        # Создаём тестовый шаблон
        tmp_id = await conn.fetchval(
            "INSERT INTO proto_templates (title) VALUES ($1) RETURNING id",
            "test-DeleteSuccess",
        )

        # Удаляем шаблон
        queries = ProtoTemplatesQueries(conn)
        status_code, message = await queries.delete(tmp_id)

        assert status_code == 200
        assert message == "Шаблон удалён"

        # Проверяем что шаблон действительно удалён
        exists = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM proto_templates WHERE id = $1)", tmp_id)
        assert exists is False


@pytest.mark.asyncio
async def test_delete_with_foreign_key_violation(db_pool):
    """Удаление шаблона с привязанными виртуальными нодами вызывает ForeignKeyViolationError"""
    async with db_pool.acquire() as conn:
        # Создаём тестовый шаблон
        tmp_id = await conn.fetchval(
            "INSERT INTO proto_templates (title) VALUES ($1) RETURNING id",
            "test-DeleteWithFK",
        )

        # Создаём физическую ноду
        node_id = await conn.fetchval(
            """
            INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "192.168.1.200",
            "10.0.0.200",
            8200,
            "test-fk-node",
            "Test FK Node",
            True,
        )

        # Создаём виртуальную ноду, привязанную к шаблону через tmp_id
        vnode_id = await conn.fetchval(
            """
            INSERT INTO nodes_protocols (node_id, tmp_id, title, sub_node_address)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            node_id,
            tmp_id,
            "Test VNode FK",
            "test-fk.example.com",
        )

        # Пытаемся удалить шаблон (должен вернуть 409)
        queries = ProtoTemplatesQueries(conn)
        status_code, message = await queries.delete(tmp_id)

        assert status_code == 409
        assert message == "Невозможно удалить: шаблон используется виртуальными нодами"

        # Проверяем что шаблон НЕ удалён
        exists = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM proto_templates WHERE id = $1)", tmp_id)
        assert exists is True


@pytest.mark.asyncio
async def test_delete_returns_200_on_success(db_pool):
    """Проверка что успешное удаление возвращает статус-код 200"""
    async with db_pool.acquire() as conn:
        tmp_id = await conn.fetchval(
            "INSERT INTO proto_templates (title) VALUES ($1) RETURNING id",
            "test-Delete200",
        )

        queries = ProtoTemplatesQueries(conn)
        status_code, _ = await queries.delete(tmp_id)

        assert status_code == 200


@pytest.mark.asyncio
async def test_delete_returns_404_when_not_found(db_pool):
    """Удаление несуществующего шаблона возвращает статус-код 404"""
    async with db_pool.acquire() as conn:
        queries = ProtoTemplatesQueries(conn)
        status_code, message = await queries.delete(999999)  # Несуществующий ID

        assert status_code == 404
        assert message == "Шаблон не найден"


@pytest.mark.asyncio
async def test_delete_returns_409_on_constraint_violation(db_pool):
    """Удаление используемого шаблона возвращает 409 с правильным сообщением"""
    async with db_pool.acquire() as conn:
        # Создаём тестовый шаблон
        tmp_id = await conn.fetchval(
            "INSERT INTO proto_templates (title) VALUES ($1) RETURNING id",
            "test-Delete409",
        )

        # Создаём физическую ноду
        node_id = await conn.fetchval(
            """
            INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            "192.168.1.201",
            "10.0.0.201",
            8201,
            "test-409-node",
            "Test 409 Node",
            True,
        )

        # Создаём виртуальную ноду с tmp_id
        await conn.execute(
            """
            INSERT INTO nodes_protocols (node_id, tmp_id, title, sub_node_address)
            VALUES ($1, $2, $3, $4)
            """,
            node_id,
            tmp_id,
            "Test VNode 409",
            "test-409.example.com",
        )

        # Удаляем
        queries = ProtoTemplatesQueries(conn)
        status_code, message = await queries.delete(tmp_id)

        assert status_code == 409
        assert "Невозможно удалить" in message
        assert "виртуальными нодами" in message
