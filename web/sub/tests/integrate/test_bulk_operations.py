"""
Integration тесты для bulk операций:
- bulk_add_users_into_single_node
- bulk_delete_users_from_single_node

Тестируем:
- Успешное выполнение + очистка outbox
- HTTP 422 (no retry)
- HTTP 500/Connection errors (retry)
- Max retries exceeded
- Проверку outbox до/после операции
"""
import pytest
from unittest.mock import AsyncMock

from web.sub.arq_tasks.traffic_reset import bulk_add_users_into_single_node
from web.sub.arq_tasks.sub_revocator import bulk_delete_users_from_single_node
from web.sub.anything import CoreProtoActions

pytestmark = pytest.mark.asyncio


class TestBulkAddUsersIntoSingleNode:
    """Тесты для bulk_add_users_into_single_node"""
    
    async def test_bulk_add_success(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Успешное добавление пользователей в ядро.
        
        Проверяем:
        - HTTP POST вызван с правильными данными
        - Outbox очищен после успеха
        - resolve_user_template корректно подставляет данные
        """
        # Arrange
        user3 = arq_test_seed['user3_active_for_add']
        users = [{
            'uuid': user3['uuid'],
            'tg_username': user3['tg_username'],
            'order_id': user3['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].status = 200
        mock_arq_ctx['aio_http'].json_data = {'success': True}
        
        # Проверяем outbox ДО выполнения
        async with db_pool.acquire() as conn:
            outbox_before = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1 AND sub_node_id = $2
            """, user3['order_active'], arq_test_seed['vnode_id_10'])
        
        assert outbox_before == 1, "Outbox должен содержать 1 запись до выполнения"
        
        # Act
        result = await bulk_add_users_into_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_add_user_script="python add.py",
            bulk_add_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            required_user_data_obj={"id": "{USER_UUID}", "email": "{USER_TG_USERNAME}"},
            constant_user_data_obj={"level": 0},
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        assert 'Пользователи добавлены' in result['message']
        
        # Проверяем что HTTP POST был вызван
        assert len(mock_arq_ctx['aio_http'].post_calls) == 1
        post_call = mock_arq_ctx['aio_http'].post_calls[0]
        assert 'http://10.0.0.100:8100' in post_call['url']
        
        # Проверяем тело запроса
        json_body = post_call['kwargs']['json']
        assert json_body['node_proto_id'] == arq_test_seed['vnode_id_10']
        assert json_body['core_lib'] == "vless"
        assert len(json_body['users']) == 1
        
        # Проверяем resolve_user_template
        user_data = json_body['users'][0]
        assert user_data['id'] == user3['uuid']  # {USER_UUID} подставлен
        assert user_data['email'] == user3['tg_username']  # {USER_TG_USERNAME} подставлен
        assert user_data['level'] == 0  # constant_user_data_obj добавлен
        
        # Проверяем outbox ПОСЛЕ выполнения (должен быть очищен)
        async with db_pool.acquire() as conn:
            outbox_after = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1 AND sub_node_id = $2
            """, user3['order_active'], arq_test_seed['vnode_id_10'])
        
        assert outbox_after == 0, "Outbox должен быть очищен после успеха"
    
    
    async def test_bulk_add_http_422_no_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        HTTP 422 от ноды - валидационная ошибка.
        
        Проверяем:
        - Возврат success=False
        - Retry НЕ создаётся
        - Outbox НЕ очищен
        """
        # Arrange
        user3 = arq_test_seed['user3_active_for_add']
        users = [{
            'uuid': user3['uuid'],
            'tg_username': user3['tg_username'],
            'order_id': user3['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].status = 422
        mock_arq_ctx['aio_http'].json_data = {'detail': 'Validation failed'}
        
        # Act
        result = await bulk_add_users_into_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_add_user_script="python add.py",
            bulk_add_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            required_user_data_obj={"id": "{USER_UUID}"},
            constant_user_data_obj={},
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is False
        assert '422' in result['message']
        
        # Проверяем что retry НЕ создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
        
        # Проверяем что outbox НЕ очищен
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1 AND sub_node_id = $2
            """, user3['order_active'], arq_test_seed['vnode_id_10'])
        
        assert outbox_count == 1, "Outbox не должен быть очищен при 422"
    
    
    async def test_bulk_add_http_500_with_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        HTTP 500 от ноды - создаётся retry задача.
        
        Проверяем:
        - enqueue_job вызван с правильными параметрами
        - defer_seconds = 120 (60 * 2^1)
        - current_attempt инкрементирован
        - Outbox НЕ очищен
        """
        # Arrange
        user3 = arq_test_seed['user3_active_for_add']
        users = [{
            'uuid': user3['uuid'],
            'tg_username': user3['tg_username'],
            'order_id': user3['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].status = 500
        mock_arq_ctx['aio_http'].json_data = {'error': 'Internal error'}
        
        # Act
        result = await bulk_add_users_into_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_add_user_script="python add.py",
            bulk_add_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            required_user_data_obj={"id": "{USER_UUID}"},
            constant_user_data_obj={},
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True  # Функция возвращает success=True даже при ошибке (retry запланирован)
        assert result['current_attempt'] == 1
        
        # Проверяем что retry создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
        call_args = mock_arq_ctx['arq_redis'].enqueue_job.call_args
        
        # Проверяем имя задачи
        assert call_args[0][0] == 'bulk_add_users_into_single_node'
        
        # Проверяем current_attempt инкрементирован
        assert call_args[0][15] == 2  # current_attempt должен быть 2
        
        # Проверяем defer_seconds
        assert call_args[1]['_defer_by'] == 120  # 60 * 2^1
        
        # Проверяем что outbox НЕ очищен
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1
            """, user3['order_active'])
        
        assert outbox_count == 2, "Outbox не должен быть очищен при ошибке"
    
    
    async def test_bulk_add_connection_error_with_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Сетевая ошибка (ClientError) - создаётся retry.
        
        Проверяем:
        - Retry создан
        - Outbox НЕ очищен
        """
        # Arrange
        user3 = arq_test_seed['user3_active_for_add']
        users = [{
            'uuid': user3['uuid'],
            'tg_username': user3['tg_username'],
            'order_id': user3['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].raise_error = True
        
        # Act
        result = await bulk_add_users_into_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_add_user_script="python add.py",
            bulk_add_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            required_user_data_obj={"id": "{USER_UUID}"},
            constant_user_data_obj={},
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что retry создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
        
        # Проверяем что outbox НЕ очищен
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1
            """, user3['order_active'])
        
        assert outbox_count == 2, "Outbox не должен быть очищен при сетевой ошибке"
    
    
    async def test_bulk_add_max_retries_exceeded(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Превышение лимита попыток (current_attempt = 3).
        
        Проверяем:
        - Retry НЕ создаётся
        - Outbox НЕ очищен (крона попробует позже)
        """
        # Arrange
        user3 = arq_test_seed['user3_active_for_add']
        users = [{
            'uuid': user3['uuid'],
            'tg_username': user3['tg_username'],
            'order_id': user3['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].status = 500
        
        # Act
        result = await bulk_add_users_into_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_add_user_script="python add.py",
            bulk_add_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            required_user_data_obj={"id": "{USER_UUID}"},
            constant_user_data_obj={},
            current_attempt=3  # Последняя попытка
        )
        
        # Assert
        assert result['success'] is True
        assert result['current_attempt'] == 3
        
        # Проверяем что retry НЕ создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
        
        # Проверяем что outbox НЕ очищен
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1
            """, user3['order_active'])
        
        assert outbox_count == 2, "Outbox не должен быть очищен после max retries"


class TestBulkDeleteUsersFromSingleNode:
    """Тесты для bulk_delete_users_from_single_node"""
    
    async def test_bulk_delete_success(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Успешное удаление пользователей из ядра.
        
        Проверяем:
        - HTTP DELETE вызван с правильными данными
        - Outbox очищен после успеха
        """
        # Arrange
        user4 = arq_test_seed['user4_active_for_delete']
        users = [{
            'uuid': user4['uuid'],
            'tg_username': user4['tg_username'],
            'order_id': user4['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].status = 200
        mock_arq_ctx['aio_http'].json_data = {'success': True}
        
        # Проверяем outbox ДО выполнения
        async with db_pool.acquire() as conn:
            outbox_before = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 2 AND sub_node_id = $2
            """, user4['order_active'], arq_test_seed['vnode_id_10'])
        
        assert outbox_before == 1, "Outbox должен содержать 1 запись до выполнения"
        
        # Act
        result = await bulk_delete_users_from_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_bulk_delete_user_script="python bulk_del.py",
            bulk_delete_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        assert 'Пользователи удалены' in result['message']
        
        # Проверяем что HTTP DELETE был вызван
        assert len(mock_arq_ctx['aio_http'].delete_calls) == 1
        delete_call = mock_arq_ctx['aio_http'].delete_calls[0]
        assert 'http://10.0.0.100:8100' in delete_call['url']
        
        # Проверяем тело запроса
        json_body = delete_call['kwargs']['json']
        assert json_body['node_proto_id'] == arq_test_seed['vnode_id_10']
        assert json_body['core_lib'] == "vless"
        assert len(json_body['users']) == 1
        assert json_body['users'][0]['uuid'] == user4['uuid']
        
        # Проверяем outbox ПОСЛЕ выполнения (должен быть очищен)
        async with db_pool.acquire() as conn:
            outbox_after = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 2 AND sub_node_id = $2
            """, user4['order_active'], arq_test_seed['vnode_id_10'])
        
        assert outbox_after == 0, "Outbox должен быть очищен после успеха"
    
    
    async def test_bulk_delete_http_422_no_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        HTTP 422 от ноды - валидационная ошибка.
        
        Проверяем:
        - Возврат success=False
        - Retry НЕ создаётся
        - Outbox НЕ очищен
        """
        # Arrange
        user4 = arq_test_seed['user4_active_for_delete']
        users = [{
            'uuid': user4['uuid'],
            'tg_username': user4['tg_username'],
            'order_id': user4['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].status = 422
        
        # Act
        result = await bulk_delete_users_from_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_bulk_delete_user_script="python bulk_del.py",
            bulk_delete_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is False
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
        
        # Проверяем что outbox НЕ очищен
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 2
            """, user4['order_active'])
        
        assert outbox_count == 2, "Outbox не должен быть очищен при 422"
    
    
    async def test_bulk_delete_http_500_with_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        HTTP 500 от ноды - создаётся retry задача.
        """
        # Arrange
        user4 = arq_test_seed['user4_active_for_delete']
        users = [{
            'uuid': user4['uuid'],
            'tg_username': user4['tg_username'],
            'order_id': user4['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].status = 500
        
        # Act
        result = await bulk_delete_users_from_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_bulk_delete_user_script="python bulk_del.py",
            bulk_delete_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что retry создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
        call_args = mock_arq_ctx['arq_redis'].enqueue_job.call_args
        
        assert call_args[0][0] == 'bulk_delete_users_from_single_node'
        assert call_args[0][13] == 2  # current_attempt должен быть 2
        assert call_args[1]['_defer_by'] == 120
    
    
    async def test_bulk_delete_connection_error_with_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Сетевая ошибка - создаётся retry.
        """
        # Arrange
        user4 = arq_test_seed['user4_active_for_delete']
        users = [{
            'uuid': user4['uuid'],
            'tg_username': user4['tg_username'],
            'order_id': user4['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].raise_error = True
        
        # Act
        result = await bulk_delete_users_from_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_bulk_delete_user_script="python bulk_del.py",
            bulk_delete_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
    
    
    async def test_bulk_delete_max_retries_exceeded(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Превышение лимита попыток (current_attempt = 3).
        """
        # Arrange
        user4 = arq_test_seed['user4_active_for_delete']
        users = [{
            'uuid': user4['uuid'],
            'tg_username': user4['tg_username'],
            'order_id': user4['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        mock_arq_ctx['aio_http'].status = 500
        
        # Act
        result = await bulk_delete_users_from_single_node(
            ctx=mock_arq_ctx,
            node_proto_id=arq_test_seed['vnode_id_10'],
            private_ip="10.0.0.100",
            api_port=8100,
            metrics_port=9090,
            proto_python_lib="vless",
            api_bulk_delete_user_script="python bulk_del.py",
            bulk_delete_script_custom_params={},
            users=users,
            reload_core_command="systemctl reload test",
            config_file_path="/etc/config.json",
            flatten_json_users_key="clients",
            flatten_user_identifier_key="email",
            current_attempt=3  # Последняя попытка
        )
        
        # Assert
        assert result['success'] is True
        assert result['current_attempt'] == 3
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
        
        # Проверяем что outbox НЕ очищен
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 2
            """, user4['order_active'])
        
        assert outbox_count == 2, "Outbox не должен быть очищен после max retries"
