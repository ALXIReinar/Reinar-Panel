"""
Integration-тесты для action_on_core_proto_by_sub_plan

Проверяет добавление/удаление пользователей в ядра протоколов на нодах.
Основная функция для Task Chaining в ARQ.
"""
import pytest
from unittest.mock import AsyncMock

from web.sub.arq_tasks.action_on_user_core_proto import action_on_core_proto_by_sub_plan
from web.sub.anything import NodeUris


class TestActionOnCoreProtoBySubPlan:
    """Тесты для action_on_core_proto_by_sub_plan"""

    @pytest.fixture
    def build_sub_nodes(self, arq_test_seed):
        """Строит sample_sub_nodes с реальными ID из БД"""
        def _build(node_proto_ids=[1, 2]):
            nodes = []
            vnode_ids = [arq_test_seed['vnode_id_10'], arq_test_seed['vnode_id_11']]
            ips = ['10.0.0.100', '10.0.0.101']
            ports = [8100, 8101]
            
            for i, node_proto_id in enumerate(node_proto_ids):
                nodes.append({
                    'node_proto_id': node_proto_id,
                    'sub_node_id': vnode_ids[i] if i < len(vnode_ids) else vnode_ids[0],
                    'private_ip': ips[i] if i < len(ips) else ips[0],
                    'api_port': ports[i] if i < len(ports) else ports[0],
                    'metrics_port': 9090 + i,
                    'proto_python_lib': 'vless',
                    'api_add_user_script': 'python /opt/add_user.py',
                    'api_delete_user_script': 'python /opt/delete_user.py',
                    'reload_core_command': 'systemctl reload xray',
                    'config_path': '/etc/xray/config.json',
                    'flatten_json_users_key': 'inbounds.0.settings.clients',
                    'flatten_user_identifier_key': 'email',
                    'required_user_data_obj': {
                        'id': '{USER_UUID}',
                        'email': '{USER_TG_USERNAME}'
                    },
                    'constant_user_data_obj': {
                        'level': 0,
                        'alterId': 0
                    },
                    'add_script_custom_params': {},
                    'delete_script_custom_params': {},
                })
            return nodes
        return _build

    async def test_action_add_single_user_success(self, mock_arq_ctx, build_sub_nodes, arq_test_seed, db_pool):
        """
        Успешное добавление пользователя на все ноды.
        
        Проверяем:
        - HTTP POST вызван для каждой ноды
        - Outbox очищен для успешных нод
        - Результат содержит success_count
        """
        # Arrange
        user_uuid = "uuid-test-123"
        tg_username = "test_user"
        mock_arq_ctx['aio_http'].status = 200
        mock_arq_ctx['aio_http'].json_data = {'success': True}
        
        sample_sub_nodes = build_sub_nodes()
        
        # Вставляем записи в outbox
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
                VALUES ($1, $2, $3, $4, $5), ($1, $2, $3, $4, $6)
            """, user_uuid, tg_username, arq_test_seed['order_id'], 1, 
                arq_test_seed['vnode_id_10'], arq_test_seed['vnode_id_11'])
        
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_uuid,
            tg_username,
            sample_sub_nodes,
            operation='add'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 2
        assert len(result['trouble_nodes']) == 0
        assert len(result['retry_nodes']) == 0
        
        # Проверяем HTTP вызовы
        assert len(mock_arq_ctx['aio_http'].post_calls) == 2
        
        # Проверяем URL первой ноды
        first_call = mock_arq_ctx['aio_http'].post_calls[0]
        assert f"http://10.0.0.100:8100{NodeUris.proto_core_add_user}" in first_call['url']
        
        # Проверяем body
        first_body = first_call['kwargs']['json']
        assert first_body['node_proto_id'] == 1
        assert first_body['user_obj']['id'] == user_uuid
        assert first_body['user_obj']['email'] == tg_username
        assert first_body['user_obj']['level'] == 0  # Из constant_user_data_obj
        
        # Проверяем что outbox очищен
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_uuid = $1",
                user_uuid
            )
        assert outbox_count == 0

    async def test_action_delete_single_user_success(self, mock_arq_ctx, build_sub_nodes, arq_test_seed, db_pool):
        """
        Успешное удаление пользователя с всех нод.
        
        Проверяем endpoint и operation='delete'
        """
        # Arrange
        user_uuid = "uuid-delete-456"
        tg_username = "delete_user"
        mock_arq_ctx['aio_http'].status = 200
        
        sample_sub_nodes = build_sub_nodes()
        
        # Вставляем записи в outbox
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
                VALUES ($1, $2, $3, $4, $5), ($1, $2, $3, $4, $6)
            """, user_uuid, tg_username, arq_test_seed['order_id'], 2,
                arq_test_seed['vnode_id_10'], arq_test_seed['vnode_id_11'])
        
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_uuid,
            tg_username,
            sample_sub_nodes,
            operation='delete'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 2
        
        # Проверяем что используется DELETE endpoint
        first_call = mock_arq_ctx['aio_http'].post_calls[0]
        assert f"http://10.0.0.100:8100{NodeUris.proto_core_delete_user}" in first_call['url']
        
        # Проверяем body содержит delete_script
        first_body = first_call['kwargs']['json']
        assert 'delete_script' in first_body
        assert first_body['delete_script'] == 'python /opt/delete_user.py'

    async def test_action_partial_success_one_node_fails(self, mock_arq_ctx, build_sub_nodes, arq_test_seed, db_pool):
        """
        Частичный успех: одна нода упала с HTTP 500.
        
        Проверяем:
        - Успешная нода: outbox очищен
        - Упавшая нода: в retry_nodes
        - enqueue_job вызван для retry
        """
        # Arrange
        user_uuid = "uuid-partial-789"
        tg_username = "partial_user"
        
        sample_sub_nodes = build_sub_nodes()
        
        # Создаём mock с разными ответами для каждой ноды
        call_count = 0
        
        def mock_post_with_different_responses(url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            # Первый вызов - успех, второй - ошибка
            if call_count == 1:
                from web.sub.tests.conftest import FakeAiohttpContext
                return FakeAiohttpContext({'success': True}, 200)
            else:
                from web.sub.tests.conftest import FakeAiohttpContext
                return FakeAiohttpContext({'error': 'Internal error'}, 500)
        
        mock_arq_ctx['aio_http'].post = mock_post_with_different_responses
        
        # Вставляем записи в outbox
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
                VALUES ($1, $2, $3, $4, $5), ($1, $2, $3, $4, $6)
            """, user_uuid, tg_username, arq_test_seed['order_id'], 1,
                arq_test_seed['vnode_id_10'], arq_test_seed['vnode_id_11'])
        
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_uuid,
            tg_username,
            sample_sub_nodes,
            operation='add'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 1
        assert len(result['retry_nodes']) == 1
        assert result['retry_nodes'][0]['node_proto_id'] == 2
        assert result['retry_nodes'][0]['status_code'] == 500
        
        # Проверяем retry enqueue
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
        call_args = mock_arq_ctx['arq_redis'].enqueue_job.call_args
        assert call_args[0][0] == 'action_on_core_proto_by_sub_plan'
        # Позиционные аргументы: func_name, uuid, tg_username, sub_nodes, operation, current_attempt
        # current_attempt находится на позиции 5 (индекс 4 после имени функции)
        # Но мы проверяем что это список нод для retry (sub_nodes)
        assert len(call_args[0][3]) == 1  # Только одна упавшая нода в retry
        # Первый retry: current_attempt=1 → 2, delay = 60 * (2 ** 1) = 120
        assert call_args[1]['_defer_by'] == 120

    async def test_action_template_validation_error(self, mock_arq_ctx, build_sub_nodes, arq_test_seed, db_pool):
        """
        Ошибка валидации шаблона: требуется tg_username, но он None.
        
        Проверяем:
        - HTTP запрос НЕ выполнен
        - trouble_nodes содержит ошибку
        - Outbox НЕ очищен
        """
        # Arrange
        user_uuid = "uuid-validation-error"
        tg_username = None  # Отсутствует, но требуется в шаблоне
        
        sample_sub_nodes = build_sub_nodes([1])  # Только одна нода
        
        # Вставляем записи в outbox
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
                VALUES ($1, $2, $3, $4, $5)
            """, user_uuid, 'null_username', arq_test_seed['order_id'], 1, arq_test_seed['vnode_id_10'])
        
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_uuid,
            tg_username,
            sample_sub_nodes,
            operation='add'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 0
        assert len(result['trouble_nodes']) == 1
        assert result['trouble_nodes'][0]['status_code'] == 400
        
        # Проверяем что HTTP запрос НЕ выполнен
        assert len(mock_arq_ctx['aio_http'].post_calls) == 0
        
        # Outbox НЕ очищен (ошибка шаблона)
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_uuid = $1",
                user_uuid
            )
        assert outbox_count == 1

    async def test_action_http_422_from_node(self, mock_arq_ctx, build_sub_nodes):
        """
        HTTP 422 от ноды (ошибка валидации конфига на ноде).
        
        Проверяем:
        - trouble_nodes содержит ошибку
        - НЕ ретраится (422 - это ошибка конфигурации)
        """
        # Arrange
        user_uuid = "uuid-422-error"
        tg_username = "user_422"
        mock_arq_ctx['aio_http'].status = 422
        mock_arq_ctx['aio_http'].json_data = {'detail': 'Validation failed'}
        
        sample_sub_nodes = build_sub_nodes([1])
        
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_uuid,
            tg_username,
            sample_sub_nodes,
            operation='add'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 0
        assert len(result['trouble_nodes']) == 1
        assert result['trouble_nodes'][0]['status_code'] == 422
        
        # НЕ ретраится (нет вызова enqueue_job)
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()

    async def test_action_retry_mechanism_exponential_backoff(self, mock_arq_ctx, build_sub_nodes):
        """
        Проверка экспоненциальной задержки retry: 60s, 120s, 240s
        """
        # Arrange
        mock_arq_ctx['aio_http'].status = 500  # Ошибка
        
        sample_sub_nodes = build_sub_nodes([1])
        
        # Act: Первая попытка (current_attempt=1)
        await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            "uuid-retry",
            "retry_user",
            sample_sub_nodes,
            operation='add',
            current_attempt=1
        )
        
        # Assert: defer_by = 60 * (2 ** 1) = 120 секунд
        call_kwargs = mock_arq_ctx['arq_redis'].enqueue_job.call_args[1]
        assert call_kwargs['_defer_by'] == 120
        
        # Reset mock
        mock_arq_ctx['arq_redis'].enqueue_job.reset_mock()
        
        # Act: Вторая попытка (current_attempt=2)
        await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            "uuid-retry",
            "retry_user",
            sample_sub_nodes,
            operation='add',
            current_attempt=2
        )
        
        # Assert: defer_by = 60 * (2 ** 2) = 240 секунд
        call_kwargs = mock_arq_ctx['arq_redis'].enqueue_job.call_args[1]
        assert call_kwargs['_defer_by'] == 240

    async def test_action_max_retries_exceeded(self, mock_arq_ctx, build_sub_nodes):
        """
        Превышение лимита попыток (max_tries=3).
        
        Проверяем:
        - enqueue_job НЕ вызван
        - Логируется ERROR (крона попробует снова)
        """
        # Arrange
        mock_arq_ctx['aio_http'].status = 500
        
        sample_sub_nodes = build_sub_nodes([1])
        
        # Act: Третья попытка (максимум)
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            "uuid-max-retry",
            "max_retry_user",
            sample_sub_nodes,
            operation='add',
            current_attempt=3
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 0
        assert len(result['retry_nodes']) == 1
        
        # enqueue_job НЕ вызван (лимит попыток)
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()

    async def test_action_empty_sub_nodes(self, mock_arq_ctx):
        """
        Пустой список нод (edge case).
        
        Должен отработать без ошибок.
        """
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            "uuid-empty",
            "empty_user",
            [],  # Пустой список
            operation='add'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 0
        assert result['total'] == 0
