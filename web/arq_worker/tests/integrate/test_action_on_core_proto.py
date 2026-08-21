"""
Integration-тесты для action_on_core_proto_by_sub_plan

Проверяет добавление/удаление пользователей в ядра протоколов на нодах.
Основная функция для Task Chaining в ARQ.
"""
import pytest

from web.arq_worker.funcs.action_on_user_core_proto import action_on_core_proto_by_sub_plan
from web.arq_worker.utils.anything import NodeUris


class TestActionOnCoreProtoBySubPlan:
    """Тесты для action_on_core_proto_by_sub_plan"""

    @pytest.fixture
    def build_sub_nodes(self, arq_test_seed, db_pool):
        """
        Загружает реальные данные нод из БД через SQL запрос get_core_proto_deps_by_user_id.
        
        Это гарантирует что тесты всегда используют актуальную структуру данных из БД.
        """
        async def _build(user_sub_id=None, operation=1, filter_node_ids=None):
            """
            Args:
                user_sub_id: ID подписки для запроса (по умолчанию из arq_test_seed)
                operation: 1=add, 2=delete
                filter_node_ids: Список node_proto_id для фильтрации результата (опционально)
            
            Returns:
                list[dict]: Список нод с полной структурой данных из БД
            """
            if user_sub_id is None:
                user_sub_id = arq_test_seed['order_id']
            
            async with db_pool.acquire() as conn:
                # Используем тот же SQL что и в реальной системе
                query = '''
                WITH insert_outbox AS (
                    INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
                    SELECT us.uuid, us.id, $2, vsp.node_proto_id
                    FROM user_subs us
                    JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = us.sub_plan_id
                    JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
                    JOIN nodes n ON n.id = np.node_id AND n.is_active = true
                    WHERE us.is_active = true AND us.id = $1
                    RETURNING id AS event_id, user_sub_id, user_uuid, node_proto_id
                ),
                pre_agg_user_injectors AS (
                    SELECT tmp_id,
                       json_agg(
                           json_build_object(
                               'flatten_array_cursor', flatten_array_cursor,
                               'extractor_script', extractor_script,
                               'libs', libs
                           )
                       ) AS user_injectors
                    FROM templates_users_extractors
                    GROUP BY tmp_id
                )
                SELECT np.id AS node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib, 
                       pt.api_bulk_delete_user_script, pt.api_bulk_add_user_script, pt.bulk_add_script_custom_params, 
                       pt.reload_core_command, np.config_path, pt.bulk_delete_script_custom_params, 
                       pt.constant_user_data_obj, pt.required_user_data_obj, np.constant_node_data_obj,
                       COALESCE(aui.user_injectors, '[]'::json) AS user_injectors, io.event_id
                FROM nodes_protocols np
                JOIN nodes n ON n.id = np.node_id AND n.is_active = true
                JOIN protocols p ON p.id = np.proto_id
                JOIN proto_templates pt ON p.tmp_id = pt.id 
                LEFT JOIN pre_agg_user_injectors aui ON aui.tmp_id = pt.id
                JOIN insert_outbox io ON io.node_proto_id = np.id
                WHERE np.user_visible = true
                '''
                rows = await conn.fetch(query, user_sub_id, operation)
                
                # Преобразуем asyncpg.Record в dict
                nodes = [dict(row) for row in rows]
                
                # Фильтруем по node_proto_id если указано
                if filter_node_ids is not None:
                    nodes = [n for n in nodes if n['node_proto_id'] in filter_node_ids]
                
                return nodes
        
        return _build

    async def test_action_add_single_user_success(self, mock_arq_ctx, build_sub_nodes, arq_test_seed, db_pool):
        """
        Успешное добавление пользователя на все ноды.
        
        Проверяем:
        - HTTP PUT вызван для каждой ноды
        - Outbox очищен для успешных нод
        - Результат содержит success_count
        """
        # Arrange
        user_uuid = "uuid-test-123"
        user_sub_id = arq_test_seed['order_id']  # Это ID активной подписки User 3
        mock_arq_ctx['aio_http'].status = 200
        mock_arq_ctx['aio_http'].json_data = {'success': True}
        
        # Загружаем реальные данные нод из БД
        sample_sub_nodes = await build_sub_nodes(user_sub_id=user_sub_id, operation=1)
        
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_uuid,
            user_sub_id,
            sample_sub_nodes,
            operation='add'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 2
        assert len(result['trouble_nodes']) == 0
        assert len(result['retry_nodes']) == 0
        
        # Проверяем HTTP PUT вызовы
        assert len(mock_arq_ctx['aio_http'].put_calls) == 2
        
        # Проверяем что HTTP PUT был вызван с правильным endpoint
        first_call = mock_arq_ctx['aio_http'].put_calls[0]
        assert NodeUris.proto_core_bulk_action in first_call['url']
        
        # Проверяем body (новая структура с action, users, user_injectors)
        first_body = first_call['kwargs']['json']
        assert first_body['node_proto_id'] == sample_sub_nodes[0]['node_proto_id']
        assert first_body['action'] == 'add'
        assert isinstance(first_body['users'], list)
        assert len(first_body['users']) == 1
        
        # Проверяем структуру пользователя в списке
        user_obj = first_body['users'][0]
        assert user_obj['user_uuid'] == user_uuid
        assert user_obj['user_sub_id'] == str(user_sub_id)
        assert user_obj['flow'] == 'xtls-rprx-vision'
        assert user_obj['level'] == 0
        
        # Проверяем наличие user_injectors
        assert 'user_injectors' in first_body
        assert isinstance(first_body['user_injectors'], list)
        
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
        user_sub_id = arq_test_seed['order_id']
        mock_arq_ctx['aio_http'].status = 200
        
        # Загружаем реальные данные нод из БД (operation=2 для delete)
        sample_sub_nodes = await build_sub_nodes(user_sub_id=user_sub_id, operation=2)
        
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_uuid,
            user_sub_id,
            sample_sub_nodes,
            operation='delete'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 2
        
        # Проверяем что используется единый эндпоинт с action='delete'
        first_call = mock_arq_ctx['aio_http'].put_calls[0]
        assert NodeUris.proto_core_bulk_action in first_call['url']
        
        # Проверяем body содержит action='delete' и bulk_delete_script
        first_body = first_call['kwargs']['json']
        assert first_body['action'] == 'delete'
        assert 'action_script' in first_body
        assert 'bulk_delete' in first_body['action_script']

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
        user_sub_id = arq_test_seed['order_id']
        
        # Загружаем реальные данные нод из БД
        sample_sub_nodes = await build_sub_nodes(user_sub_id=user_sub_id, operation=1)
        
        # Создаём mock с разными ответами для каждой ноды
        call_count = 0
        
        def mock_put_with_different_responses(url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            # Первый вызов - успех, второй - ошибка
            if call_count == 1:
                from web.arq_worker.tests.conftest import FakeAiohttpContext
                return FakeAiohttpContext({'success': True}, 200)
            else:
                from web.arq_worker.tests.conftest import FakeAiohttpContext
                return FakeAiohttpContext({'error': 'Internal error'}, 500)
        
        mock_arq_ctx['aio_http'].put = mock_put_with_different_responses
        
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_uuid,
            user_sub_id,
            sample_sub_nodes,
            operation='add'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 1
        assert len(result['retry_nodes']) == 1
        assert result['retry_nodes'][0]['status_code'] == 500
        
        # Проверяем retry enqueue
        mock_arq_ctx['arq_redis'].enqueue_job.assert_called_once()
        call_args = mock_arq_ctx['arq_redis'].enqueue_job.call_args
        assert call_args[0][0] == 'action_on_core_proto_by_sub_plan'
        # Позиционные аргументы: func_name, uuid, user_sub_id, sub_nodes, operation, current_attempt
        # Проверяем что это список нод для retry (sub_nodes на позиции 3)
        assert len(call_args[0][3]) == 1  # Только одна упавшая нода в retry
        # Первый retry: current_attempt=1 → 2, delay = 60 * (2 ** 1) = 120
        assert call_args[1]['_defer_by'] == 120

    async def test_action_template_validation_error(self, mock_arq_ctx, build_sub_nodes, arq_test_seed, db_pool):
        """
        Ошибка валидации шаблона: требуется user_sub_id, но он None.
        
        Проверяем:
        - HTTP запрос НЕ выполнен
        - trouble_nodes содержит ошибку
        - Outbox НЕ очищен (для данного теста)
        """
        # Arrange: Используем user 4 с простой структурой
        user_data = arq_test_seed['user4_active_for_delete']
        
        # Загружаем реальные данные нод из БД (это создаст outbox с реальным UUID)
        sample_sub_nodes = await build_sub_nodes(
            user_sub_id=user_data['user_sub_id'], 
            operation=1,
            filter_node_ids=[arq_test_seed['vnode_id_10']]  # Только одна нода
        )
        
        # Получаем event_id который был создан в outbox
        async with db_pool.acquire() as conn:
            event_id_before = await conn.fetchval(
                "SELECT id FROM sub_nodes_outbox WHERE user_sub_id = $1 AND node_proto_id = $2 ORDER BY id DESC LIMIT 1",
                user_data['user_sub_id'],
                arq_test_seed['vnode_id_10']
            )
        
        # Act: Передаём user_sub_id=None, что вызовет ошибку валидации
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_data['uuid'],
            None,  # None здесь вызовет ошибку валидации
            sample_sub_nodes,
            operation='add'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 0
        assert len(result['trouble_nodes']) == 1
        assert result['trouble_nodes'][0]['status_code'] == 400
        
        # Проверяем что HTTP запрос НЕ выполнен
        assert len(mock_arq_ctx['aio_http'].put_calls) == 0
        
        # Outbox НЕ очищен - запись всё ещё существует
        async with db_pool.acquire() as conn:
            event_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM sub_nodes_outbox WHERE id = $1)",
                event_id_before
            )
        assert event_exists is True

    async def test_action_http_422_from_node(self, mock_arq_ctx, build_sub_nodes, arq_test_seed):
        """
        HTTP 422 от ноды (ошибка валидации конфига на ноде).
        
        Проверяем:
        - trouble_nodes содержит ошибку
        - НЕ ретраится (422 - это ошибка конфигурации)
        """
        # Arrange
        user_uuid = "uuid-422-error"
        user_sub_id = arq_test_seed['order_id']
        mock_arq_ctx['aio_http'].status = 422
        mock_arq_ctx['aio_http'].json_data = {'detail': 'Validation failed'}
        
        # Загружаем реальные данные нод из БД (только одна нода)
        sample_sub_nodes = await build_sub_nodes(
            user_sub_id=user_sub_id,
            operation=1,
            filter_node_ids=[arq_test_seed['vnode_id_10']]
        )
        
        # Act
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            user_uuid,
            user_sub_id,
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

    async def test_action_retry_mechanism_exponential_backoff(self, mock_arq_ctx, build_sub_nodes, arq_test_seed):
        """
        Проверка экспоненциальной задержки retry: 60s, 120s, 240s
        """
        # Arrange
        mock_arq_ctx['aio_http'].status = 500  # Ошибка
        user_sub_id = arq_test_seed['order_id']
        
        # Загружаем реальные данные нод из БД (только одна нода)
        sample_sub_nodes = await build_sub_nodes(
            user_sub_id=user_sub_id,
            operation=1,
            filter_node_ids=[arq_test_seed['vnode_id_10']]
        )
        
        # Act: Первая попытка (current_attempt=1)
        await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            "uuid-retry",
            200,
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
            200,
            sample_sub_nodes,
            operation='add',
            current_attempt=2
        )
        
        # Assert: defer_by = 60 * (2 ** 2) = 240 секунд
        call_kwargs = mock_arq_ctx['arq_redis'].enqueue_job.call_args[1]
        assert call_kwargs['_defer_by'] == 240

    async def test_action_max_retries_exceeded(self, mock_arq_ctx, build_sub_nodes, arq_test_seed):
        """
        Превышение лимита попыток (max_tries=3).
        
        Проверяем:
        - enqueue_job НЕ вызван
        - Логируется ERROR (крона попробует снова)
        """
        # Arrange
        mock_arq_ctx['aio_http'].status = 500
        user_sub_id = arq_test_seed['order_id']
        
        # Загружаем реальные данные нод из БД (только одна нода)
        sample_sub_nodes = await build_sub_nodes(
            user_sub_id=user_sub_id,
            operation=1,
            filter_node_ids=[arq_test_seed['vnode_id_10']]
        )
        
        # Act: Третья попытка (максимум)
        result = await action_on_core_proto_by_sub_plan(
            mock_arq_ctx,
            "uuid-max-retry",
            300,
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
            400,
            [],  # Пустой список
            operation='add'
        )
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 0
        assert result['total'] == 0
