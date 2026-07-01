"""
E2E тесты для admin_request_bulk_action_users и цепочки bulk операций.

Проверяем полный flow:
1. Админка создаёт outbox (имитируем вручную)
2. admin_request_bulk_action_users ставит задачи в ARQ
3. bulk_add/bulk_delete выполняются
4. Outbox очищается после успеха
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from web.sub.arq_tasks.admin_actions import admin_request_bulk_action_users
from web.sub.arq_tasks.traffic_reset import bulk_add_users_into_single_node
from web.sub.arq_tasks.sub_revocator import bulk_delete_users_from_single_node

pytestmark = pytest.mark.asyncio


class TestAdminBulkPipeline:
    """E2E тесты для admin_request_bulk_action_users"""
    
    async def test_admin_add_users_full_pipeline(self, arq_ctx, arq_test_seed, db_pool):
        """
        Полный E2E flow для ADD операции через админку.
        
        Flow:
        1. Админка создаёт outbox
        2. admin_request_bulk_action_users ставит задачи в ARQ
        3. bulk_add_users_into_single_node выполняется
        4. Outbox очищается
        """
        # Arrange: подготовка данных пользователя
        user3 = arq_test_seed['user3_active_for_add']
        users_input = [{
            'order_id': user3['order_active'],
            'sub_plan_id': arq_test_seed['plan_id'],
            'user_id': user3['user_id']
        }]
        
        # Outbox уже создан в arq_test_seed (operation=1 для ADD)
        
        # Проверяем outbox ДО выполнения
        async with db_pool.acquire() as conn:
            outbox_before = await conn.fetch("""
                SELECT * FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1
                ORDER BY sub_node_id
            """, user3['order_active'])
        
        assert len(outbox_before) == 2, "Должно быть 2 записи в outbox (на 2 ноды)"
        
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
        
        # Act 1: Вызываем admin_request_bulk_action_users
        await admin_request_bulk_action_users(
            arq_ctx,
            'add',       # action
            users_input  # users
        )
        
        # Assert 1: Проверяем что задачи поставлены в ARQ
        assert len(enqueued_jobs) == 2, "Должно быть 2 задачи (на 2 ноды)"
        
        # Проверяем что обе задачи для bulk_add_users_into_single_node
        for job_data in enqueued_jobs:
            assert job_data['args'][0] == 'bulk_add_users_into_single_node'
        
        # Act 2: Выполняем bulk операции вручную (имитация ARQ worker)
        for job_data in enqueued_jobs:
            args = job_data['args']
            
            # Извлекаем параметры из enqueue_job
            result = await bulk_add_users_into_single_node(
                ctx=arq_ctx,
                node_proto_id=args[1],      # node_proto_id
                private_ip=args[2],          # private_ip
                api_port=args[3],            # api_port
                metrics_port=args[4],        # metrics_port
                proto_python_lib=args[5],    # proto_python_lib
                api_add_user_script=args[6], # api_add_user_script
                bulk_add_script_custom_params=args[7], # custom_params
                users=args[8],               # users
                reload_core_command=args[9], # reload_core_command
                config_file_path=args[10],   # config_file_path
                flatten_json_users_key=args[11], # flatten_json_users_key
                flatten_user_identifier_key=args[12], # flatten_user_identifier_key
                required_user_data_obj={"id": "{USER_UUID}", "email": "{USER_TG_USERNAME}"},
                constant_user_data_obj={"level": 0},
                current_attempt=1
            )
            
            assert result['success'] is True
        
        # Assert 2: Проверяем что HTTP POST был вызван для каждой ноды
        assert len(arq_ctx['aio_http'].post_calls) == 2
        
        # Assert 3: Проверяем что outbox очищен после успеха
        async with db_pool.acquire() as conn:
            outbox_after = await conn.fetch("""
                SELECT * FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1
            """, user3['order_active'])
        
        assert len(outbox_after) == 0, "Outbox должен быть очищен после успешного выполнения"
    
    
    async def test_admin_delete_users_full_pipeline(self, arq_ctx, arq_test_seed, db_pool):
        """
        Полный E2E flow для DELETE операции через админку.
        """
        # Arrange
        user4 = arq_test_seed['user4_active_for_delete']
        users_input = [{
            'order_id': user4['order_active'],
            'sub_plan_id': arq_test_seed['plan_id'],
            'user_id': user4['user_id']
        }]
        
        # Outbox уже создан в arq_test_seed (operation=2 для DELETE)
        
        # Проверяем outbox ДО выполнения
        async with db_pool.acquire() as conn:
            outbox_before = await conn.fetch("""
                SELECT * FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 2
                ORDER BY sub_node_id
            """, user4['order_active'])
        
        assert len(outbox_before) == 2, "Должно быть 2 записи в outbox (на 2 ноды)"
        
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
        
        # Act 1: Вызываем admin_request_bulk_action_users
        await admin_request_bulk_action_users(
            arq_ctx,
            'delete',    # action
            users_input  # users
        )
        
        # Assert 1: Проверяем что задачи поставлены в ARQ
        assert len(enqueued_jobs) == 2, "Должно быть 2 задачи (на 2 ноды)"
        
        for job_data in enqueued_jobs:
            assert job_data['args'][0] == 'bulk_delete_users_from_single_node'
        
        # Act 2: Выполняем bulk операции вручную
        for job_data in enqueued_jobs:
            args = job_data['args']
            
            result = await bulk_delete_users_from_single_node(
                ctx=arq_ctx,
                node_proto_id=args[1],
                private_ip=args[2],
                api_port=args[3],
                metrics_port=args[4],
                proto_python_lib=args[5],
                api_bulk_delete_user_script=args[6],
                bulk_delete_script_custom_params=args[7],
                users=args[8],
                reload_core_command=args[9],
                config_file_path=args[10],
                flatten_json_users_key=args[11],
                flatten_user_identifier_key=args[12],
                current_attempt=1
            )
            
            assert result['success'] is True
        
        # Assert 2: Проверяем что HTTP DELETE был вызван
        assert len(arq_ctx['aio_http'].delete_calls) == 2
        
        # Assert 3: Проверяем что outbox очищен
        async with db_pool.acquire() as conn:
            outbox_after = await conn.fetch("""
                SELECT * FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 2
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
        users_input = [{
            'order_id': user3['order_active'],
            'sub_plan_id': arq_test_seed['plan_id'],
            'user_id': user3['user_id']
        }]
        
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
        
        # Act: Вызываем admin_request_bulk_action_users
        await admin_request_bulk_action_users(
            arq_ctx,
            'add',       # action
            users_input  # users
        )
        
        # Assert 1: Проверяем что задачи созданы для обеих нод
        assert len(enqueued_jobs) == 2, "Должно быть 2 задачи (vnode_10 и vnode_11)"
        
        # Проверяем что node_proto_id разные
        node_ids = [job['args'][1] for job in enqueued_jobs]
        assert arq_test_seed['vnode_id_10'] in node_ids
        assert arq_test_seed['vnode_id_11'] in node_ids
        
        # Проверяем что каждая задача содержит пользователя
        for job_data in enqueued_jobs:
            users_list = job_data['args'][8]  # users параметр
            assert len(users_list) == 1
            assert users_list[0]['uuid'] == user3['uuid']
            assert users_list[0]['tg_username'] == user3['tg_username']
        
        # Act 2: Выполняем bulk операции для обеих нод
        for job_data in enqueued_jobs:
            args = job_data['args']
            
            await bulk_add_users_into_single_node(
                ctx=arq_ctx,
                node_proto_id=args[1],
                private_ip=args[2],
                api_port=args[3],
                metrics_port=args[4],
                proto_python_lib=args[5],
                api_add_user_script=args[6],
                bulk_add_script_custom_params=args[7],
                users=args[8],
                reload_core_command=args[9],
                config_file_path=args[10],
                flatten_json_users_key=args[11],
                flatten_user_identifier_key=args[12],
                required_user_data_obj={"id": "{USER_UUID}"},
                constant_user_data_obj={},
                current_attempt=1
            )
        
        # Assert 2: Проверяем что outbox очищен для ОБЕИХ нод
        async with db_pool.acquire() as conn:
            outbox_remaining = await conn.fetch("""
                SELECT * FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1
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
            # Создаём отдельный план подписки
            invisible_plan_id = await conn.fetchval("""
                INSERT INTO sub_plans (title, description, ttl_days, cost, traffic_limit_day, is_active)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, "Invisible Plan", "Plan for invisible node test", 30, 500, 10240, True)
            
            # Связываем план ТОЛЬКО с невидимой нодой
            await conn.execute("""
                INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id)
                VALUES ($1, $2)
            """, arq_test_seed['vnode_id_invisible'], invisible_plan_id)
            
            # Создаём пользователя
            user_invisible_id = await conn.fetchval("""
                INSERT INTO users (tg_id, tg_username, uuid, b64_id, is_deleted)
                VALUES ($1, $2, $3, $4, false)
                RETURNING id
            """, 999999, "invisible_node_user", "uuid-invisible-test", "b64-invisible-test")
            
            # Создаём подписку на новый план
            order_invisible = await conn.fetchval("""
                INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
                VALUES ($1, $2, true, 2, now() + interval '30 days')
                RETURNING id
            """, user_invisible_id, invisible_plan_id)
            
            # Создаём outbox для невидимой ноды (должен быть проигнорирован)
            await conn.execute("""
                INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
                VALUES ($1, $2, $3, 1, $4)
            """, "uuid-invisible-test", "invisible_node_user", order_invisible, 
                arq_test_seed['vnode_id_invisible'])
        
        users_input = [{
            'order_id': order_invisible,
            'sub_plan_id': invisible_plan_id,  # Используем новый plan_id
            'user_id': user_invisible_id
        }]
        
        # Mock для arq.enqueue_job
        enqueued_jobs = []
        
        async def mock_enqueue_job(*args, **kwargs):
            job_mock = MagicMock()
            job_mock.job_id = f"test-job-{len(enqueued_jobs)}"
            enqueued_jobs.append({'args': args, 'kwargs': kwargs, 'job': job_mock})
            return job_mock
        
        arq_ctx['arq_redis'].enqueue_job = mock_enqueue_job
        
        # Act: Вызываем admin_request_bulk_action_users
        await admin_request_bulk_action_users(
            arq_ctx,
            'add',       # action
            users_input  # users
        )
        
        # Assert: Проверяем что задачи НЕ поставлены (нода отфильтрована в SQL)
        assert len(enqueued_jobs) == 0, "Не должно быть задач для невидимых нод"
        
        # Проверяем что outbox НЕ тронут (задачи не выполнялись)
        async with db_pool.acquire() as conn:
            outbox_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE order_id = $1 AND operation = 1
            """, order_invisible)
        
        assert outbox_count == 1, "Outbox не должен быть тронут для невидимых нод"
