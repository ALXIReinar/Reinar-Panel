"""
E2E тесты для admin_request_bulk_action_users и цепочки bulk операций.

Проверяем полный flow:
1. Админка создаёт outbox (имитируем вручную)
2. admin_request_bulk_action_users ставит задачи в ARQ
3. bulk_add/bulk_delete выполняются
4. Outbox очищается после успеха
"""
import pytest
from unittest.mock import MagicMock

from web.arq_worker.funcs.admin_actions import admin_request_bulk_action_users
from web.arq_worker.funcs.bulk_action_on_core_proto import bulk_action_users_by_node

pytestmark = pytest.mark.asyncio


class TestAdminBulkPipeline:
    """E2E тесты для admin_request_bulk_action_users"""
    
    async def test_admin_add_users_full_pipeline(self, arq_ctx, arq_test_seed, db_pool):
        """
        Полный E2E flow для ADD операции через админку.
        
        Flow:
        1. Админка создаёт outbox
        2. admin_request_bulk_action_users ставит задачи в ARQ
        3. bulk_action_users_by_node (operation=ADD) выполняется
        4. Outbox очищается
        """
        # Arrange: подготовка данных пользователя
        user3 = arq_test_seed['user3_active_for_add']
        
        # Outbox уже создан в arq_test_seed (operation=1 для ADD)
        
        # Получаем outbox event_ids для передачи в функцию
        async with db_pool.acquire() as conn:
            outbox_before = await conn.fetch("""
                SELECT id, * FROM sub_nodes_outbox
                WHERE user_sub_id = $1 AND operation = 1
                ORDER BY node_proto_id
            """, user3['order_active'])
        
        assert len(outbox_before) == 2, "Должно быть 2 записи в outbox (на 2 ноды)"
        
        # Извлекаем event_ids из outbox
        outbox_event_ids = [row['id'] for row in outbox_before]
        
        # Mock для arq.enqueue_job чтобы захватить параметры
        enqueued_jobs = []
        
        async def mock_enqueue_job(*args, **kwargs):
            job_mock = MagicMock()
            job_mock.job_id = f"test-job-{len(enqueued_jobs)}"
            enqueued_jobs.append({
                'args': args,
                'kwargs': kwargs,
                'job': job_mock
            })
            return job_mock
        
        arq_ctx['arq_redis'].enqueue_job = mock_enqueue_job
        arq_ctx['aio_http'].status = 200
        arq_ctx['aio_http'].json_data = {'success': True}
        
        # Act 1: Вызываем admin_request_bulk_action_users с event_ids
        await admin_request_bulk_action_users(
            arq_ctx,
            'add',            # action
            outbox_event_ids  # outbox_event_ids (list[int])
        )
        
        # Assert 1: Проверяем что задачи поставлены в ARQ
        assert len(enqueued_jobs) == 2, "Должно быть 2 задачи (на 2 ноды)"
        
        # Проверяем что обе задачи для bulk_action_users_by_node с operation=1 (ADD)
        for job_data in enqueued_jobs:
            assert job_data['args'][0] == 'bulk_action_users_by_node'
            assert job_data['args'][8] == 1, "operation должна быть 1 (ADD)"
        
        # Act 2: Выполняем bulk операции вручную (имитация ARQ worker)
        for job_data in enqueued_jobs:
            args = job_data['args']
            
            # Извлекаем параметры из enqueue_job
            result = await bulk_action_users_by_node(
                ctx=arq_ctx,
                node_proto_id=args[1],      # node_proto_id
                private_ip=args[2],          # private_ip
                api_port=args[3],            # api_port
                metrics_port=args[4],        # metrics_port
                proto_python_lib=args[5],    # proto_python_lib
                api_bulk_action_script=args[6], # api_bulk_action_script
                bulk_action_script_custom_params=args[7], # custom_params
                operation=args[8],           # operation
                users=args[9],               # users
                reload_core_command=args[10], # reload_core_command
                config_file_path=args[11],   # config_file_path
                user_injectors=args[12],     # user_injectors
                required_user_data_obj=args[13], # required_user_data_obj
                constant_user_data_obj=args[14], # constant_user_data_obj
                current_attempt=1
            )
            
            assert result['success'] is True
        
        # Assert 2: Проверяем что HTTP PUT был вызван для каждой ноды
        assert len(arq_ctx['aio_http'].put_calls) == 2
        
        # Assert 3: Проверяем что outbox очищен после успеха
        async with db_pool.acquire() as conn:
            outbox_after = await conn.fetch("""
                SELECT * FROM sub_nodes_outbox
                WHERE user_sub_id = $1 AND operation = 1
            """, user3['order_active'])
        
        assert len(outbox_after) == 0, "Outbox должен быть очищен после успешного выполнения"
    
    
    async def test_admin_delete_users_full_pipeline(self, arq_ctx, arq_test_seed, db_pool):
        """
        Полный E2E flow для DELETE операции через админку.
        """
        # Arrange
        user4 = arq_test_seed['user4_active_for_delete']
        
        # Outbox уже создан в arq_test_seed (operation=2 для DELETE)
        
        # Получаем outbox event_ids для передачи в функцию
        async with db_pool.acquire() as conn:
            outbox_before = await conn.fetch("""
                SELECT id, * FROM sub_nodes_outbox
                WHERE user_sub_id = $1 AND operation = 2
                ORDER BY node_proto_id
            """, user4['order_active'])
        
        assert len(outbox_before) == 2, "Должно быть 2 записи в outbox (на 2 ноды)"
        
        # Извлекаем event_ids из outbox
        outbox_event_ids = [row['id'] for row in outbox_before]
        
        # Mock для arq.enqueue_job
        enqueued_jobs = []
        
        async def mock_enqueue_job(*args, **kwargs):
            job_mock = MagicMock()
            job_mock.job_id = f"test-job-{len(enqueued_jobs)}"
            enqueued_jobs.append({
                'args': args,
                'kwargs': kwargs,
                'job': job_mock
            })
            return job_mock
        
        arq_ctx['arq_redis'].enqueue_job = mock_enqueue_job
        arq_ctx['aio_http'].status = 200
        arq_ctx['aio_http'].json_data = {'success': True}
        
        # Act 1: Вызываем admin_request_bulk_action_users с event_ids
        await admin_request_bulk_action_users(
            arq_ctx,
            'delete',         # action
            outbox_event_ids  # outbox_event_ids (list[int])
        )
        
        # Assert 1: Проверяем что задачи поставлены в ARQ
        assert len(enqueued_jobs) == 2, "Должно быть 2 задачи (на 2 ноды)"
        
        for job_data in enqueued_jobs:
            assert job_data['args'][0] == 'bulk_action_users_by_node'
            assert job_data['args'][8] == 2, "operation должна быть 2 (DELETE)"
        
        # Act 2: Выполняем bulk операции вручную
        for job_data in enqueued_jobs:
            args = job_data['args']
            
            result = await bulk_action_users_by_node(
                ctx=arq_ctx,
                node_proto_id=args[1],
                private_ip=args[2],
                api_port=args[3],
                metrics_port=args[4],
                proto_python_lib=args[5],
                api_bulk_action_script=args[6],
                bulk_action_script_custom_params=args[7],
                operation=args[8],
                users=args[9],
                reload_core_command=args[10],
                config_file_path=args[11],
                user_injectors=args[12],
                required_user_data_obj=args[13],
                constant_user_data_obj=args[14],
                current_attempt=1
            )
            
            assert result['success'] is True
        
        # Assert 2: Проверяем что HTTP PUT был вызван
        assert len(arq_ctx['aio_http'].put_calls) == 2
        
        # Assert 3: Проверяем что outbox очищен
        async with db_pool.acquire() as conn:
            outbox_after = await conn.fetch("""
                SELECT * FROM sub_nodes_outbox
                WHERE user_sub_id = $1 AND operation = 2
            """, user4['order_active'])
        
        assert len(outbox_after) == 0, "Outbox должен быть очищен после успешного выполнения"
    
    
    async def test_admin_action_multiple_nodes(self, arq_ctx, arq_test_seed, db_pool):
        """
        Проверяем что пользователи правильно распределяются на несколько нод.
        
        Проверяем:
        - Задачи созданы для каждой ноды
        - Каждая нода получает правильный список пользователей
        - Outbox очищается для всех нод
        """
        # Arrange: используем user3 который привязан к 2 нодам
        user3 = arq_test_seed['user3_active_for_add']
        
        # Получаем outbox event_ids
        async with db_pool.acquire() as conn:
            outbox_records = await conn.fetch("""
                SELECT id FROM sub_nodes_outbox
                WHERE user_sub_id = $1 AND operation = 1
                ORDER BY node_proto_id
            """, user3['order_active'])
        
        outbox_event_ids = [row['id'] for row in outbox_records]
        
        # Mock для arq.enqueue_job
        enqueued_jobs = []
        
        async def mock_enqueue_job(*args, **kwargs):
            job_mock = MagicMock()
            job_mock.job_id = f"test-job-{len(enqueued_jobs)}"
            enqueued_jobs.append({
                'args': args,
                'kwargs': kwargs,
                'job': job_mock
            })
            return job_mock
        
        arq_ctx['arq_redis'].enqueue_job = mock_enqueue_job
        arq_ctx['aio_http'].status = 200
        
        # Act: Вызываем admin_request_bulk_action_users с event_ids
        await admin_request_bulk_action_users(
            arq_ctx,
            'add',            # action
            outbox_event_ids  # outbox_event_ids (list[int])
        )
        
        # Assert 1: Проверяем что задачи созданы для обеих нод
        assert len(enqueued_jobs) == 2, "Должно быть 2 задачи (vnode_10 и vnode_11)"
        
        # Проверяем что node_proto_id разные
        node_ids = [job['args'][1] for job in enqueued_jobs]
        assert arq_test_seed['vnode_id_10'] in node_ids
        assert arq_test_seed['vnode_id_11'] in node_ids
        
        # Проверяем что каждая задача содержит пользователя
        for job_data in enqueued_jobs:
            users_list = job_data['args'][9]  # users параметр на позиции 9
            assert len(users_list) == 1
            assert users_list[0]['uuid'] == user3['uuid']
            assert users_list[0]['user_sub_id'] == user3['order_active']
        
        # Act 2: Выполняем bulk операции для обеих нод
        for job_data in enqueued_jobs:
            args = job_data['args']
            
            await bulk_action_users_by_node(
                ctx=arq_ctx,
                node_proto_id=args[1],
                private_ip=args[2],
                api_port=args[3],
                metrics_port=args[4],
                proto_python_lib=args[5],
                api_bulk_action_script=args[6],
                bulk_action_script_custom_params=args[7],
                operation=args[8],
                users=args[9],
                reload_core_command=args[10],
                config_file_path=args[11],
                user_injectors=args[12],
                required_user_data_obj=args[13],
                constant_user_data_obj=args[14],
                current_attempt=1
            )
        
        # Assert 2: Проверяем что outbox очищен для ОБЕИХ нод
        async with db_pool.acquire() as conn:
            outbox_remaining = await conn.fetch("""
                SELECT * FROM sub_nodes_outbox
                WHERE user_sub_id = $1 AND operation = 1
            """, user3['order_active'])
        
        assert len(outbox_remaining) == 0, "Outbox должен быть очищен для всех нод"
    
    
    async def test_admin_action_filters_inactive_nodes(self, arq_ctx, arq_test_seed, db_pool):
        """
        Проверяем что SQL фильтрует неактивные/невидимые ноды.
        
        Сценарий:
        - Создаём пользователя с подпиской на невидимую ноду
        - Вызываем admin_request_bulk_action_users
        - Проверяем что задачи НЕ поставлены (нода отфильтрована)
        """
        # Arrange: создаём отдельный план подписки только для невидимой ноды
        async with db_pool.acquire() as conn:
            # Создаём отдельный план подписки (теперь без ttl_days, cost и т.д.)
            invisible_plan_id = await conn.fetchval("""
                INSERT INTO sub_plans (title, description, is_active, position)
                VALUES ($1, $2, $3, $4)
                RETURNING id
            """, "Invisible Plan", "Plan for invisible node test", True, 99)
            
            # Создаём оффер для плана
            invisible_offer_id = await conn.fetchval("""
                INSERT INTO sub_plan_offers (
                    sub_plan_id, ttl_days, cost,
                    traffic_limit_day_mb, traffic_limit_mb,
                    infinite_traffic, infinite_expire, is_active, position
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
            """, invisible_plan_id, 30, 500, 10240, None, False, False, True, 1)
            
            # Связываем план ТОЛЬКО с невидимой нодой
            await conn.execute("""
                INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id)
                VALUES ($1, $2)
            """, arq_test_seed['vnode_id_invisible'], invisible_plan_id)
            
            # Создаём пользователя
            user_invisible_id = await conn.fetchval("""
                INSERT INTO users (tg_id, tg_username, is_deleted)
                VALUES ($1, $2, false)
                RETURNING id
            """, 999999, "invisible_node_user")
            
            # Создаём платёж (копируем данные из оффера)
            pay_order_invisible = await conn.fetchval("""
                INSERT INTO pay_orders (
                    user_id, status,
                    infinite_expire, infinite_traffic,
                    traffic_limit_mb, traffic_limit_day_mb,
                    ttl_days, cost
                )
                SELECT $1, 2,
                    infinite_expire, infinite_traffic,
                    traffic_limit_mb, traffic_limit_day_mb,
                    ttl_days, cost
                FROM sub_plan_offers
                WHERE id = $2
                RETURNING id
            """, user_invisible_id, invisible_offer_id)
            
            # Создаём подписку на новый план
            order_invisible = await conn.fetchval("""
                INSERT INTO user_subs (user_id, sub_plan_id, order_id, is_active, expire_date,
                                       uuid, b64_id, infinite_traffic, infinite_expire,
                                       traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited)
                VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
                RETURNING id
            """, user_invisible_id, invisible_plan_id, pay_order_invisible,
                 "uuid-invisible-test", "b64-invisible-test")
            
            # Создаём outbox для невидимой ноды (должен быть проигнорирован)
            outbox_id = await conn.fetchval("""
                INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
                VALUES ($1, $2, 1, $3)
                RETURNING id
            """, "uuid-invisible-test", order_invisible, 
                arq_test_seed['vnode_id_invisible'])
        
        outbox_event_ids = [outbox_id]
        
        # Mock для arq.enqueue_job
        enqueued_jobs = []
        
        async def mock_enqueue_job(*args, **kwargs):
            job_mock = MagicMock()
            job_mock.job_id = f"test-job-{len(enqueued_jobs)}"
            enqueued_jobs.append({'args': args, 'kwargs': kwargs, 'job': job_mock})
            return job_mock
        
        arq_ctx['arq_redis'].enqueue_job = mock_enqueue_job
        
        # Act: Вызываем admin_request_bulk_action_users с event_ids
        await admin_request_bulk_action_users(
            arq_ctx,
            'add',            # action
            outbox_event_ids  # outbox_event_ids (list[int])
        )
        
        # Assert: Проверяем что задачи НЕ поставлены (нода отфильтрована в SQL)
        assert len(enqueued_jobs) == 0, "Не должно быть задач для невидимых нод"
        
        # Проверяем что outbox НЕ тронут (задачи не выполнялись)
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE user_sub_id = $1 AND operation = 1
            """, order_invisible)
        
        assert outbox_count == 1, "Outbox не должен быть тронут для невидимых нод"
