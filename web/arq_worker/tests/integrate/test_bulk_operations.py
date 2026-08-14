"""
Integration тесты для bulk операций:
- bulk_action_users_by_node с operation=1 (ADD)
- bulk_action_users_by_node с operation=2 (DELETE)

Тестируем:
- Успешное выполнение + очистка outbox
- HTTP 422 (no retry)
- HTTP 500/Connection errors (retry)
- Max retries exceeded
- Проверку outbox до/после операции

Все тесты используют реальные данные из БД через get_meta_for_bulk.
"""
import pytest

from web.arq_worker.funcs.bulk_action_on_core_proto import bulk_action_users_by_node
from web.arq_worker.utils.anything import CoreProtoActions
from web.arq_worker.data.postgres import PgSql

pytestmark = pytest.mark.asyncio


class TestBulkActionUsersAdd:
    """Тесты для bulk_action_users_by_node с operation=ADD"""
    
    async def _load_node_data_from_db(self, db_pool, arq_test_seed, operation=1):
        """Helper: загружает данные ноды из БД через get_meta_for_bulk"""
        user_data = arq_test_seed['user3_active_for_add'] if operation == 1 else arq_test_seed['user4_active_for_delete']
        
        # Получаем event_id из существующей outbox записи
        async with db_pool.acquire() as conn:
            event_id = await conn.fetchval("""
                SELECT id FROM sub_nodes_outbox
                WHERE user_sub_id = $1 AND operation = $2 AND node_proto_id = $3
                LIMIT 1
            """, user_data['user_sub_id'], operation, arq_test_seed['vnode_id_10'])
        
        if not event_id:
            raise RuntimeError(f"Outbox не содержит запись для user_sub_id={user_data['user_sub_id']}, operation={operation}")
        
        # Загружаем реальные данные через SQL get_meta_for_bulk
        async with db_pool.acquire() as conn:
            pg_sql = PgSql(conn)
            nodes_data = await pg_sql.core_proto_bulk.get_meta_for_bulk([event_id])
        
        if len(nodes_data) == 0:
            raise RuntimeError(f"get_meta_for_bulk не вернул данных для event_id={event_id}")
        
        return dict(nodes_data[0]), event_id, user_data
    
    async def test_bulk_add_success(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Успешное добавление пользователей в ядро.
        
        Проверяем:
        - HTTP PUT вызван с правильными данными
        - Outbox очищен после успеха
        - Данные загружены из БД через get_meta_for_bulk
        """
        # Arrange
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed, operation=1)
        
        mock_arq_ctx['aio_http'].status = 200
        mock_arq_ctx['aio_http'].json_data = {'success': True}
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_add_user_script'],
            bulk_action_script_custom_params=node_data['bulk_add_script_custom_params'],
            operation=CoreProtoActions.add,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что HTTP PUT был вызван (новый эндпоинт)
        assert len(mock_arq_ctx['aio_http'].put_calls) == 1
        put_call = mock_arq_ctx['aio_http'].put_calls[0]
        assert node_data['private_ip'] in put_call['url']
        assert '/proto_core/user/bulk/action' in put_call['url']
        
        # Проверяем тело запроса
        json_body = put_call['kwargs']['json']
        assert json_body['action'] == CoreProtoActions.add
        assert len(json_body['users']) == 1
        assert 'user_injectors' in json_body
        
        # Проверяем create_vpn_like_user подставил данные
        user_obj = json_body['users'][0]
        assert user_obj['user_uuid'] == user_data['uuid']
        assert user_obj['user_sub_id'] == str(user_data['user_sub_id'])
        
        # Проверяем outbox ПОСЛЕ выполнения (должен быть очищен)
        async with db_pool.acquire() as conn:
            event_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_nodes_outbox WHERE id = $1)",
                event_id
            )
        assert event_exists is False, "Outbox должен быть очищен после успеха"
    
    async def test_bulk_add_http_422_no_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        HTTP 422 от ноды - валидационная ошибка.
        
        Проверяем:
        - Возврат success=False
        - Retry НЕ создаётся
        - Outbox НЕ очищен
        """
        # Arrange
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed, operation=1)
        
        mock_arq_ctx['aio_http'].status = 422
        mock_arq_ctx['aio_http'].json_data = {'detail': 'Validation failed'}
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_add_user_script'],
            bulk_action_script_custom_params=node_data['bulk_add_script_custom_params'],
            operation=CoreProtoActions.add,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is False
        assert '422' in result['message']
        
        # Проверяем что retry НЕ создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
        
        # Outbox НЕ очищен при 422
        async with db_pool.acquire() as conn:
            event_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_nodes_outbox WHERE id = $1)",
                event_id
            )
        assert event_exists is True, "Outbox не должен быть очищен при 422"
    
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
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed, operation=1)
        
        mock_arq_ctx['aio_http'].status = 500
        mock_arq_ctx['aio_http'].json_data = {'error': 'Internal error'}
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_add_user_script'],
            bulk_action_script_custom_params=node_data['bulk_add_script_custom_params'],
            operation=CoreProtoActions.add,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True  # Функция возвращает success=True даже при ошибке (retry запланирован)
        assert result['current_attempt'] == 1
        
        # Проверяем что retry создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
        call_args = mock_arq_ctx['arq_redis'].enqueue_job.call_args
        
        # Проверяем имя задачи
        assert call_args[0][0] == 'bulk_action_users_by_node'
        
        # Проверяем current_attempt инкрементирован (позиция 15 в параметрах)
        assert call_args[0][15] == 2  # current_attempt должен быть 2
        
        # Проверяем defer_seconds
        assert call_args[1]['_defer_by'] == 120  # 60 * 2^1
        
        # Outbox НЕ очищен при ошибке
        async with db_pool.acquire() as conn:
            event_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_nodes_outbox WHERE id = $1)",
                event_id
            )
        assert event_exists is True, "Outbox не должен быть очищен при ошибке"
    
    async def test_bulk_add_connection_error_with_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Сетевая ошибка (ClientError) - создаётся retry.
        
        Проверяем:
        - Retry создан
        - Outbox НЕ очищен
        """
        # Arrange
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed, operation=1)
        
        mock_arq_ctx['aio_http'].raise_error = True
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_add_user_script'],
            bulk_action_script_custom_params=node_data['bulk_add_script_custom_params'],
            operation=CoreProtoActions.add,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что retry создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
        
        # Outbox НЕ очищен при сетевой ошибке
        async with db_pool.acquire() as conn:
            event_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_nodes_outbox WHERE id = $1)",
                event_id
            )
        assert event_exists is True, "Outbox не должен быть очищен при сетевой ошибке"
    
    async def test_bulk_add_max_retries_exceeded(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Превышение лимита попыток (current_attempt = 3).
        
        Проверяем:
        - Retry НЕ создаётся
        - Outbox НЕ очищен (крона попробует позже)
        """
        # Arrange
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed, operation=1)
        
        mock_arq_ctx['aio_http'].status = 500
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_add_user_script'],
            bulk_action_script_custom_params=node_data['bulk_add_script_custom_params'],
            operation=CoreProtoActions.add,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=3  # Последняя попытка
        )
        
        # Assert
        assert result['success'] is True
        assert result['current_attempt'] == 3
        
        # Проверяем что retry НЕ создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
        
        # Outbox НЕ очищен после max retries
        async with db_pool.acquire() as conn:
            event_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_nodes_outbox WHERE id = $1)",
                event_id
            )
        assert event_exists is True, "Outbox не должен быть очищен после max retries"


class TestBulkActionUsersDelete:
    """Тесты для bulk_action_users_by_node с operation=DELETE"""
    
    async def _load_node_data_from_db(self, db_pool, arq_test_seed):
        """Helper: загружает данные ноды из БД для DELETE операции"""
        user_data = arq_test_seed['user4_active_for_delete']
        
        # Получаем event_id из существующей outbox записи
        async with db_pool.acquire() as conn:
            event_id = await conn.fetchval("""
                SELECT id FROM sub_nodes_outbox
                WHERE user_sub_id = $1 AND operation = 2 AND node_proto_id = $2
                LIMIT 1
            """, user_data['user_sub_id'], arq_test_seed['vnode_id_10'])
        
        if not event_id:
            raise RuntimeError(f"Outbox не содержит запись для user_sub_id={user_data['user_sub_id']}, operation=2")
        
        # Загружаем реальные данные через SQL get_meta_for_bulk
        async with db_pool.acquire() as conn:
            pg_sql = PgSql(conn)
            nodes_data = await pg_sql.core_proto_bulk.get_meta_for_bulk([event_id])
        
        if len(nodes_data) == 0:
            raise RuntimeError(f"get_meta_for_bulk не вернул данных для event_id={event_id}")
        
        return dict(nodes_data[0]), event_id, user_data
    
    async def test_bulk_delete_success(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Успешное удаление пользователей из ядра.
        
        Проверяем:
        - HTTP PUT вызван с правильными данными
        - Outbox очищен после успеха
        """
        # Arrange
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed)
        
        mock_arq_ctx['aio_http'].status = 200
        mock_arq_ctx['aio_http'].json_data = {'success': True}
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_delete_user_script'],
            bulk_action_script_custom_params=node_data['bulk_delete_script_custom_params'],
            operation=CoreProtoActions.delete,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что HTTP PUT был вызван
        assert len(mock_arq_ctx['aio_http'].put_calls) == 1
        put_call = mock_arq_ctx['aio_http'].put_calls[0]
        assert node_data['private_ip'] in put_call['url']
        
        # Проверяем тело запроса
        json_body = put_call['kwargs']['json']
        assert json_body['action'] == CoreProtoActions.delete
        assert len(json_body['users']) == 1
        
        # Проверяем outbox ПОСЛЕ выполнения (должен быть очищен)
        async with db_pool.acquire() as conn:
            event_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_nodes_outbox WHERE id = $1)",
                event_id
            )
        assert event_exists is False, "Outbox должен быть очищен после успеха"
    
    async def test_bulk_delete_http_422_no_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """HTTP 422 от ноды - валидационная ошибка."""
        # Arrange
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed)
        
        mock_arq_ctx['aio_http'].status = 422
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_delete_user_script'],
            bulk_action_script_custom_params=node_data['bulk_delete_script_custom_params'],
            operation=CoreProtoActions.delete,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is False
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
        
        # Outbox НЕ очищен при 422
        async with db_pool.acquire() as conn:
            event_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_nodes_outbox WHERE id = $1)",
                event_id
            )
        assert event_exists is True, "Outbox не должен быть очищен при 422"
    
    async def test_bulk_delete_http_500_with_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """HTTP 500 от ноды - создаётся retry задача."""
        # Arrange
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed)
        
        mock_arq_ctx['aio_http'].status = 500
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_delete_user_script'],
            bulk_action_script_custom_params=node_data['bulk_delete_script_custom_params'],
            operation=CoreProtoActions.delete,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что retry создан
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
        call_args = mock_arq_ctx['arq_redis'].enqueue_job.call_args
        
        assert call_args[0][0] == 'bulk_action_users_by_node'
        assert call_args[0][15] == 2  # current_attempt должен быть 2
        assert call_args[1]['_defer_by'] == 120
    
    async def test_bulk_delete_connection_error_with_retry(self, mock_arq_ctx, arq_test_seed, db_pool):
        """Сетевая ошибка - создаётся retry."""
        # Arrange
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed)
        
        mock_arq_ctx['aio_http'].raise_error = True
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_delete_user_script'],
            bulk_action_script_custom_params=node_data['bulk_delete_script_custom_params'],
            operation=CoreProtoActions.delete,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=1
        )
        
        # Assert
        assert result['success'] is True
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
    
    async def test_bulk_delete_max_retries_exceeded(self, mock_arq_ctx, arq_test_seed, db_pool):
        """Превышение лимита попыток (current_attempt = 3)."""
        # Arrange
        node_data, event_id, user_data = await self._load_node_data_from_db(db_pool, arq_test_seed)
        
        mock_arq_ctx['aio_http'].status = 500
        
        # Act
        result = await bulk_action_users_by_node(
            ctx=mock_arq_ctx,
            node_proto_id=node_data['node_proto_id'],
            private_ip=node_data['private_ip'],
            api_port=node_data['api_port'],
            metrics_port=node_data['metrics_port'],
            proto_python_lib=node_data['proto_python_lib'],
            api_bulk_action_script=node_data['api_bulk_delete_user_script'],
            bulk_action_script_custom_params=node_data['bulk_delete_script_custom_params'],
            operation=CoreProtoActions.delete,
            users=node_data['users'],
            reload_core_command=node_data['reload_core_command'],
            config_file_path=node_data['config_path'],
            user_injectors=node_data['user_injectors'],
            required_user_data_obj=node_data['required_user_data_obj'],
            constant_user_data_obj=node_data['constant_user_data_obj'],
            current_attempt=3  # Последняя попытка
        )
        
        # Assert
        assert result['success'] is True
        assert result['current_attempt'] == 3
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
        
        # Outbox НЕ очищен после max retries
        async with db_pool.acquire() as conn:
            event_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_nodes_outbox WHERE id = $1)",
                event_id
            )
        assert event_exists is True, "Outbox не должен быть очищен после max retries"
