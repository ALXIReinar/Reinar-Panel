"""
Integration тесты для pointed_bulk_action - функции-менеджера для массовых операций.

Тестируем:
- Подготовку данных через SQL get_users_by_sub_plan
- Группировку пользователей по нодам
- Постановку задач в ARQ для bulk операций
- Фильтрацию неактивных/невидимых нод и удалённых пользователей
"""
import pytest

from web.sub.arq_tasks.pounted_bulk.pointed_bulk_actions import pointed_bulk_action

pytestmark = pytest.mark.asyncio


class TestPointedBulkAction:
    """Тесты для функции-менеджера pointed_bulk_action"""
    
    async def test_pointed_bulk_add_action(self, mock_arq_ctx, pointed_bulk_seed, db_pool):
        """
        Проверка ADD операции через pointed_bulk_action.
        
        Сценарий:
        - 2 пользователя с outbox записями для ADD (operation=1)
        - Пользователи распределены на 2 разные ноды
        - Ожидаем 2 ARQ задачи (по одной на каждую ноду)
        - Проверяем параметры задач (node_proto_id, users, api_bulk_add_user_script)
        """
        # Arrange
        outbox_ids = [
            pointed_bulk_seed['outbox_user3_add_vnode10'],
            pointed_bulk_seed['outbox_user5_add_vnode11']
        ]
        
        # Act
        result = await pointed_bulk_action(
            ctx=mock_arq_ctx,
            outbox_event_ids=outbox_ids,
            action='add'
        )
        
        # Assert
        assert result['success'] is True
        assert 'Бульк запросы полетели' in result['message']
        
        # Проверяем что arq.enqueue_job вызван 2 раза (для каждой ноды)
        assert mock_arq_ctx['arq_redis'].enqueue_job.call_count == 2
        
        # Проверяем параметры каждого вызова
        calls = mock_arq_ctx['arq_redis'].enqueue_job.call_args_list
        
        # Первая нода (vnode_id_10)
        call_1 = calls[0]
        assert call_1[0][0] == 'bulk_add_users_into_single_node'  # Имя функции
        assert call_1[0][1] == pointed_bulk_seed['vnode_id_10']  # node_proto_id
        assert call_1[0][2] == "10.0.0.100"  # private_ip
        assert call_1[0][6] == "python bulk_add.py"  # api_bulk_add_user_script
        
        # Проверяем что в users есть правильный пользователь
        users_node_10 = call_1[0][8]  # users параметр
        assert len(users_node_10) == 1
        assert users_node_10[0]['uuid'] == pointed_bulk_seed['user3_uuid']
        assert users_node_10[0]['user_sub_id'] == pointed_bulk_seed['user3_order_active']
        
        # Вторая нода (vnode_id_11)
        call_2 = calls[1]
        assert call_2[0][0] == 'bulk_add_users_into_single_node'
        assert call_2[0][1] == pointed_bulk_seed['vnode_id_11']
        assert call_2[0][6] == "python bulk_add.py"
        
        users_node_11 = call_2[0][8]
        assert len(users_node_11) == 1
        assert users_node_11[0]['uuid'] == pointed_bulk_seed['user5_uuid']
    
    
    async def test_pointed_bulk_delete_action(self, mock_arq_ctx, pointed_bulk_seed, db_pool):
        """
        Проверка DELETE операции через pointed_bulk_action.
        
        Сценарий:
        - 2 пользователя с outbox записями для DELETE (operation=2)
        - Ожидаем ARQ задачи с bulk_delete_users_from_single_node
        """
        # Arrange
        outbox_ids = [
            pointed_bulk_seed['outbox_user4_delete_vnode10'],
            pointed_bulk_seed['outbox_user6_delete_vnode11']
        ]
        
        # Act
        result = await pointed_bulk_action(
            ctx=mock_arq_ctx,
            outbox_event_ids=outbox_ids,
            action='delete'
        )
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что arq.enqueue_job вызван 2 раза
        assert mock_arq_ctx['arq_redis'].enqueue_job.call_count == 2
        
        calls = mock_arq_ctx['arq_redis'].enqueue_job.call_args_list
        
        # Проверяем что вызывается bulk_delete_users_from_single_node
        call_1 = calls[0]
        assert call_1[0][0] == 'bulk_delete_users_from_single_node'
        assert call_1[0][1] == pointed_bulk_seed['vnode_id_10']
        assert call_1[0][6] == "python bulk_del.py"  # api_bulk_delete_user_script
        
        users_node_10 = call_1[0][8]
        assert len(users_node_10) == 1
        assert users_node_10[0]['uuid'] == pointed_bulk_seed['user4_uuid']
        
        call_2 = calls[1]
        assert call_2[0][0] == 'bulk_delete_users_from_single_node'
        assert call_2[0][1] == pointed_bulk_seed['vnode_id_11']
    
    
    async def test_pointed_bulk_empty_outbox_ids(self, mock_arq_ctx, pointed_bulk_seed, db_pool):
        """
        Проверка обработки пустого списка outbox_ids.
        
        Ожидаем:
        - success=False
        - ARQ задачи НЕ созданы
        """
        # Act
        result = await pointed_bulk_action(
            ctx=mock_arq_ctx,
            outbox_event_ids=[],
            action='add'
        )
        
        # Assert
        assert result['success'] is False
        assert 'Нет оутбоксов' in result['message']
        
        # Проверяем что ARQ задачи НЕ созданы
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
    
    
    async def test_pointed_bulk_groups_by_nodes(self, mock_arq_ctx, pointed_bulk_seed, db_pool):
        """
        Проверка группировки пользователей по нодам.
        
        Сценарий:
        - 3 пользователя: 2 на vnode_10, 1 на vnode_11
        - Ожидаем 2 ARQ задачи
        - Проверяем количество пользователей в каждой задаче
        """
        # Arrange - создаём дополнительного пользователя на vnode_10
        async with db_pool.acquire() as conn:
            # User 7 на той же ноде что и User 3
            user7_id = await conn.fetchval("""
                INSERT INTO users (tg_id, tg_username, is_deleted)
                VALUES ($1, $2, false)
                RETURNING id
            """, 100007, "user7_grouping")
            
            pay_order7 = await conn.fetchval("""
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
            """, user7_id, pointed_bulk_seed['offer_id'])
            
            user7_row = await conn.fetchrow("""
                INSERT INTO user_subs (
                    user_id, sub_plan_id, order_id, is_active, expire_date,
                    uuid, b64_id, infinite_traffic, infinite_expire,
                    traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
                )
                VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
                RETURNING id, uuid
            """, user7_id, pointed_bulk_seed['plan_id'], pay_order7, "uuid-pointed-user7", "b64-user7")
            
            user7_order = user7_row['id']
            user7_uuid = user7_row['uuid']
            
            # Создаём outbox записи для vnode_10
            outbox_user7_vnode10 = await conn.fetchval("""
                INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
                VALUES ($1, $2, 1, $3)
                RETURNING id
            """, user7_uuid, user7_order, pointed_bulk_seed['vnode_id_10'])
        
        outbox_ids = [
            pointed_bulk_seed['outbox_user3_add_vnode10'],  # User 3 на vnode_10
            outbox_user7_vnode10,                           # User 7 на vnode_10
            pointed_bulk_seed['outbox_user5_add_vnode11']   # User 5 на vnode_11
        ]
        
        # Act
        result = await pointed_bulk_action(
            ctx=mock_arq_ctx,
            outbox_event_ids=outbox_ids,
            action='add'
        )
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что созданы задачи для 2 нод
        assert mock_arq_ctx['arq_redis'].enqueue_job.call_count == 2
        
        calls = mock_arq_ctx['arq_redis'].enqueue_job.call_args_list
        
        # Находим задачу для vnode_10 (должна содержать 2 пользователей)
        vnode_10_call = [c for c in calls if c[0][1] == pointed_bulk_seed['vnode_id_10']][0]
        users_vnode_10 = vnode_10_call[0][8]
        assert len(users_vnode_10) == 2, "vnode_10 должна содержать 2 пользователей"
        
        # Проверяем UUID пользователей
        uuids_vnode_10 = {u['uuid'] for u in users_vnode_10}
        assert pointed_bulk_seed['user3_uuid'] in uuids_vnode_10
        assert user7_uuid in uuids_vnode_10
        
        # Находим задачу для vnode_11 (должна содержать 1 пользователя)
        vnode_11_call = [c for c in calls if c[0][1] == pointed_bulk_seed['vnode_id_11']][0]
        users_vnode_11 = vnode_11_call[0][8]
        assert len(users_vnode_11) == 1, "vnode_11 должна содержать 1 пользователя"
        assert users_vnode_11[0]['uuid'] == pointed_bulk_seed['user5_uuid']
    
    
    async def test_pointed_bulk_filters_inactive_nodes(self, mock_arq_ctx, pointed_bulk_seed, db_pool):
        """
        Проверка фильтрации неактивных физических нод (is_active=false).
        
        Сценарий:
        - Создаём outbox запись на неактивную ноду
        - Ожидаем что SQL get_users_by_sub_plan НЕ вернёт эту ноду
        - ARQ задачи НЕ созданы для этой ноды
        """
        # Arrange - outbox_user8_inactive_node уже создан в фикстуре
        outbox_ids = [pointed_bulk_seed['outbox_user8_inactive_node']]
        
        # Act
        result = await pointed_bulk_action(
            ctx=mock_arq_ctx,
            outbox_event_ids=outbox_ids,
            action='add'
        )
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что ARQ задачи НЕ созданы (нода неактивна)
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
    
    
    async def test_pointed_bulk_filters_invisible_nodes(self, mock_arq_ctx, pointed_bulk_seed, db_pool):
        """
        Проверка фильтрации невидимых нод (user_visible=false).
        
        Сценарий:
        - Создаём outbox запись на ноду с user_visible=false
        - Ожидаем что SQL НЕ вернёт эту ноду
        """
        # Arrange - outbox_user9_invisible_node уже создан в фикстуре
        outbox_ids = [pointed_bulk_seed['outbox_user9_invisible_node']]
        
        # Act
        result = await pointed_bulk_action(
            ctx=mock_arq_ctx,
            outbox_event_ids=outbox_ids,
            action='add'
        )
        
        # Assert
        assert result['success'] is True
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
    
    
    async def test_pointed_bulk_filters_deleted_users(self, mock_arq_ctx, pointed_bulk_seed, db_pool):
        """
        Проверка фильтрации удалённых пользователей (is_deleted=true).
        
        Сценарий:
        - Создаём outbox запись для пользователя с is_deleted=true
        - Ожидаем что SQL НЕ вернёт этого пользователя
        """
        # Arrange - outbox_user10_deleted уже создан в фикстуре
        outbox_ids = [pointed_bulk_seed['outbox_user10_deleted']]
        
        # Act
        result = await pointed_bulk_action(
            ctx=mock_arq_ctx,
            outbox_event_ids=outbox_ids,
            action='delete'
        )
        
        # Assert
        assert result['success'] is True
        mock_arq_ctx['arq_redis'].enqueue_job.assert_not_called()
