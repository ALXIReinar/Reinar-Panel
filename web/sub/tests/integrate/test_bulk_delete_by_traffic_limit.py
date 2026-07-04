"""
Integration тесты для bulk_delete_by_traffic_limit (уровень 3 task chaining).

Тестируем:
- Получение виртуальных нод по outbox_event_ids
- Группировку пользователей по нодам
- Постановку задач bulk_delete_users_from_single_node в ARQ
- Фильтрацию неактивных/невидимых нод
"""
import pytest
from unittest.mock import MagicMock

from web.sub.arq_tasks.metrics_collector import bulk_delete_by_traffic_limit

pytestmark = pytest.mark.asyncio


class TestBulkDeleteByTrafficLimit:
    """Интеграционные тесты для bulk_delete_by_traffic_limit"""
    
    async def test_bulk_delete_by_traffic_limit_success(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Успешная постановка задач на удаление пользователей, превысивших лимит трафика.
        
        Flow:
        1. Создаём outbox записи (имитация update_traffic)
        2. Вызываем bulk_delete_by_traffic_limit с outbox_event_ids
        3. Проверяем что задачи поставлены в ARQ
        4. Проверяем группировку пользователей по нодам
        """
        # Arrange: создаём outbox записи для user3 (превышение трафика)
        user3 = arq_test_seed['user3_active_for_add']
        
        async with db_pool.acquire() as conn:
            # Создаём outbox записи с operation=2 (DELETE) для обеих нод
            outbox_ids = []
            for vnode_id in [arq_test_seed['vnode_id_10'], arq_test_seed['vnode_id_11']]:
                outbox_id = await conn.fetchval("""
                    INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
                    VALUES ($1, $2, $3, 2, $4)
                    RETURNING id
                """, user3['uuid'], user3['tg_username'], user3['order_active'], vnode_id)
                outbox_ids.append(outbox_id)
        
        # Mock для arq.enqueue_job
        enqueued_jobs = []
        
        async def mock_enqueue_job(*args, **kwargs):
            job_mock = MagicMock()
            job_mock.job_id = f"test-job-{len(enqueued_jobs)}"
            enqueued_jobs.append({
                'args': args,
                'kwargs': kwargs,
                'job': job_mock,
                'function_name': args[0],
                'node_proto_id': args[1] if len(args) > 1 else None
            })
            return job_mock
        
        mock_arq_ctx['arq_redis'].enqueue_job = mock_enqueue_job
        
        # Act: вызываем bulk_delete_by_traffic_limit
        result = await bulk_delete_by_traffic_limit(
            mock_arq_ctx,
            outbox_ids
        )
        
        # Assert: проверяем результат
        assert result['success'] is True
        assert result['total_nodes'] == 2, "Должно быть 2 ноды"
        
        # Проверяем что задачи поставлены в ARQ
        assert len(enqueued_jobs) == 2, "Должно быть 2 задачи (по одной на каждую ноду)"
        
        # Проверяем что все задачи для bulk_delete_users_from_single_node
        for job_data in enqueued_jobs:
            assert job_data['function_name'] == 'bulk_delete_users_from_single_node'
            assert job_data['node_proto_id'] in [arq_test_seed['vnode_id_10'], arq_test_seed['vnode_id_11']]
            
            # Проверяем параметры задачи
            users_list = job_data['args'][8]  # users параметр
            assert len(users_list) == 1, "Должен быть 1 пользователь на ноде"
            assert users_list[0]['uuid'] == user3['uuid']
            assert users_list[0]['tg_username'] == user3['tg_username']
    
    
    async def test_bulk_delete_by_traffic_limit_multiple_nodes(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Проверяем правильную группировку пользователей по нодам.
        
        Сценарий:
        - 2 пользователя (user3 и user4) на разных/общих нодах
        - Проверяем что каждая нода получает правильный список пользователей
        """
        # Arrange: создаём outbox для двух пользователей
        user3 = arq_test_seed['user3_active_for_add']
        user4 = arq_test_seed['user4_active_for_delete']
        
        async with db_pool.acquire() as conn:
            outbox_ids = []
            
            # User3 на обе ноды
            for vnode_id in [arq_test_seed['vnode_id_10'], arq_test_seed['vnode_id_11']]:
                outbox_id = await conn.fetchval("""
                    INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
                    VALUES ($1, $2, $3, 2, $4)
                    RETURNING id
                """, user3['uuid'], user3['tg_username'], user3['order_active'], vnode_id)
                outbox_ids.append(outbox_id)
            
            # User4 только на vnode_10
            outbox_id = await conn.fetchval("""
                INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
                VALUES ($1, $2, $3, 2, $4)
                RETURNING id
            """, user4['uuid'], user4['tg_username'], user4['order_active'], arq_test_seed['vnode_id_10'])
            outbox_ids.append(outbox_id)
        
        # Mock для arq.enqueue_job
        enqueued_jobs = []
        
        async def mock_enqueue_job(*args, **kwargs):
            job_mock = MagicMock()
            job_mock.job_id = f"test-job-{len(enqueued_jobs)}"
            enqueued_jobs.append({
                'args': args,
                'node_proto_id': args[1],
                'users': args[8]
            })
            return job_mock
        
        mock_arq_ctx['arq_redis'].enqueue_job = mock_enqueue_job
        
        # Act
        result = await bulk_delete_by_traffic_limit(
            mock_arq_ctx,
            outbox_ids
        )
        
        # Assert
        assert result['success'] is True
        assert len(enqueued_jobs) == 2, "Должно быть 2 задачи (на 2 ноды)"
        
        # Проверяем группировку пользователей
        for job_data in enqueued_jobs:
            if job_data['node_proto_id'] == arq_test_seed['vnode_id_10']:
                # vnode_10 должна иметь 2 пользователей (user3 + user4)
                assert len(job_data['users']) == 2, "vnode_10 должна иметь 2 пользователей"
                uuids = {u['uuid'] for u in job_data['users']}
                assert user3['uuid'] in uuids
                assert user4['uuid'] in uuids
            elif job_data['node_proto_id'] == arq_test_seed['vnode_id_11']:
                # vnode_11 должна иметь только user3
                assert len(job_data['users']) == 1, "vnode_11 должна иметь 1 пользователя"
                assert job_data['users'][0]['uuid'] == user3['uuid']
    
    
    async def test_bulk_delete_by_traffic_limit_filters_inactive_nodes(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Проверяем что SQL фильтрует невидимые/неактивные ноды.
        
        Сценарий:
        - Создаём outbox записи на невидимую ноду
        - Проверяем что задачи НЕ поставлены
        """
        # Arrange: создаём отдельный план только для невидимой ноды
        async with db_pool.acquire() as conn:
            # Создаём план подписки только для невидимой ноды
            invisible_plan_id = await conn.fetchval("""
                INSERT INTO sub_plans (title, description, ttl_days, cost, traffic_limit_day, is_active)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, "Invisible Traffic Plan", "Plan for invisible node test", 30, 500, 10240, True)
            
            # Связываем план ТОЛЬКО с невидимой нодой
            invisible_sub_node_id = await conn.fetchval("""
                INSERT INTO vnodes_sub_plans (node_proto_id, sub_plan_id)
                VALUES ($1, $2)
                RETURNING id
            """, arq_test_seed['vnode_id_invisible'], invisible_plan_id)
            
            # Создаём пользователя с подпиской на невидимую ноду
            user_invisible_id = await conn.fetchval("""
                INSERT INTO users (tg_id, tg_username, uuid, b64_id, is_deleted)
                VALUES ($1, $2, $3, $4, false)
                RETURNING id
            """, 888888, "traffic_invisible_user", "uuid-traffic-invisible", "b64-traffic-invisible")
            
            order_invisible = await conn.fetchval("""
                INSERT INTO payed_subs (user_id, sub_plan_id, is_active, status, expire_date)
                VALUES ($1, $2, true, 2, now() + interval '30 days')
                RETURNING id
            """, user_invisible_id, invisible_plan_id)
            
            # Создаём outbox запись на невидимую ноду
            outbox_id_invisible = await conn.fetchval("""
                INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
                VALUES ($1, $2, $3, 2, $4)
                RETURNING id
            """, "uuid-traffic-invisible", "traffic_invisible_user", order_invisible, invisible_sub_node_id)
        
        # Mock для arq.enqueue_job
        enqueued_jobs = []
        
        async def mock_enqueue_job(*args, **kwargs):
            job_mock = MagicMock()
            job_mock.job_id = f"test-job-{len(enqueued_jobs)}"
            enqueued_jobs.append({'args': args})
            return job_mock
        
        mock_arq_ctx['arq_redis'].enqueue_job = mock_enqueue_job
        
        # Act
        result = await bulk_delete_by_traffic_limit(
            mock_arq_ctx,
            [outbox_id_invisible]
        )
        
        # Assert: проверяем что задачи НЕ поставлены (невидимая нода отфильтрована)
        assert result['success'] is True
        assert result['total_nodes'] == 0, "Не должно быть нод (невидимая нода отфильтрована)"
        assert len(enqueued_jobs) == 0, "Не должно быть задач для невидимых нод"
    
    
    async def test_bulk_delete_by_traffic_limit_empty_outbox_ids(self, mock_arq_ctx, arq_test_seed, db_pool):
        """
        Edge case: пустой массив outbox_event_ids.
        
        Проверяем graceful handling.
        """
        # Mock для arq.enqueue_job
        enqueued_jobs = []
        
        async def mock_enqueue_job(*args, **kwargs):
            job_mock = MagicMock()
            job_mock.job_id = f"test-job-{len(enqueued_jobs)}"
            enqueued_jobs.append({'args': args})
            return job_mock
        
        mock_arq_ctx['arq_redis'].enqueue_job = mock_enqueue_job
        
        # Act: вызываем с пустым массивом
        result = await bulk_delete_by_traffic_limit(
            mock_arq_ctx,
            []  # Пустой массив
        )
        
        # Assert
        assert result['success'] is True
        assert result['total_nodes'] == 0, "Не должно быть нод для пустого массива"
        assert len(enqueued_jobs) == 0, "Не должно быть задач для пустого массива"
