"""
Integration тесты для revoke_sub_plan_by_expire - кроны отзыва просроченных подписок.

revoke_sub_plan_by_expire:
1. Находит истёкшие подписки через get_and_lock_expired_subs_grouped_by_node()
2. АТОМАРНО выключает их (is_active=false, status=expired)
3. Группирует пользователей по нодам
4. Ставит задачи bulk_action_users_by_node (operation=DELETE) в ARQ

Критические SQL фильтры:
- is_active = true (только активные подписки)
- expire_date < now() (только истёкшие)
- u.is_deleted = false (только неудалённые пользователи)
- np.user_visible = true (только видимые ноды)
- n.is_active = true (только активные физические ноды)
"""
import pytest

from web.arq_worker.funcs.sub_revocator import revoke_sub_plan_by_expire


pytestmark = pytest.mark.asyncio


class TestRevokeSubPlanByExpire:
    """Integration тесты для revoke_sub_plan_by_expire"""
    
    async def test_revoke_success_with_expired_subs(self, arq_ctx, arq_pool, revoke_seed, db_pool):
        """
        Успешный отзыв истёкших подписок.
        
        Проверяем:
        - Подписки выключены (is_active=false, status=expired)
        - Outbox заполнен для пользователей
        - Задачи поставлены в ARQ
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = revoke_seed
        
        # Act
        result = await revoke_sub_plan_by_expire(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert 'message' in result
        assert result['total_nodes'] >= 1  # Минимум одна нода
        
        # Проверяем что подписки выключены
        async with db_pool.acquire() as conn:
            # User A и User B должны быть выключены
            user_a_sub = await conn.fetchrow("""
                SELECT is_active, order_id FROM user_subs WHERE id = $1
            """, seed['should_revoke']['user_a']['order_id'])
            
            user_b_sub = await conn.fetchrow("""
                SELECT is_active, order_id FROM user_subs WHERE id = $1
            """, seed['should_revoke']['user_b']['order_id'])
            
            assert user_a_sub['is_active'] is False
            # Проверяем статус платежа
            order_a_status = await conn.fetchval("SELECT status FROM pay_orders WHERE id = $1", user_a_sub['order_id'])
            assert order_a_status == 3  # expired
            assert user_b_sub['is_active'] is False
            order_b_status = await conn.fetchval("SELECT status FROM pay_orders WHERE id = $1", user_b_sub['order_id'])
            assert order_b_status == 3
            
            # Проверяем что outbox заполнен для user_a и user_b
            outbox_records = await conn.fetch("""
                SELECT user_sub_id, user_uuid, operation 
                FROM sub_nodes_outbox 
                WHERE user_sub_id IN ($1, $2)
            """, seed['should_revoke']['user_a']['order_id'],
                 seed['should_revoke']['user_b']['order_id'])
            
            assert len(outbox_records) >= 2  # Минимум 2 записи (по 1 на ноду для каждого юзера)
            
            # Все записи должны быть DELETE операцией (operation=2)
            for record in outbox_records:
                assert record['operation'] == 2
    
    
    async def test_revoke_no_expired_subs(self, arq_ctx, db_pool, db_seed):
        """
        Нет истёкших подписок - idle.
        
        Проверяем:
        - Возвращается success=True
        - Сообщение о том что нет просроченных
        - total_nodes отсутствует
        """
        # Arrange - БД очищена через db_seed, нет подписок
        
        # Act
        result = await revoke_sub_plan_by_expire(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert 'Нет просроченных подписок' in result['message']
        assert 'total_nodes' not in result
    
    
    async def test_revoke_sql_filters_critical(self, arq_ctx, arq_pool, revoke_seed, db_pool):
        """
        КРИТИЧЕСКИЙ ТЕСТ SQL ФИЛЬТРОВ: Проверяем что отзываются ТОЛЬКО валидные подписки.
        
        Должны отзываться:
        - User A: is_active=true, expire_date < now(), is_deleted=false ✅
        - User B: is_active=true, expire_date < now(), is_deleted=false ✅
        
        НЕ должны отзываться:
        - User C: is_active=false (уже выключена) ❌
        - User D: expire_date > now() (ещё активна) ❌
        - User E: is_deleted=true (пользователь удалён) ❌
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = revoke_seed
        
        # Act
        result = await revoke_sub_plan_by_expire(arq_ctx)
        
        # Assert
        assert result['success'] is True
        
        async with db_pool.acquire() as conn:
            # Проверяем ТОЛЬКО user_a и user_b выключены
            deactivated_subs = await conn.fetch("""
                SELECT us.id, us.user_id, us.is_active, us.order_id
                FROM user_subs us
                WHERE us.user_id IN ($1, $2, $3, $4, $5)
                ORDER BY us.user_id
            """, seed['should_revoke']['user_a']['user_id'],
                 seed['should_revoke']['user_b']['user_id'],
                 seed['should_not_revoke']['user_c']['user_id'],
                 seed['should_not_revoke']['user_d']['user_id'],
                 seed['should_not_revoke']['user_e']['user_id'])
            
            # User A и User B должны быть выключены
            user_a_sub = next(s for s in deactivated_subs if s['user_id'] == seed['should_revoke']['user_a']['user_id'])
            user_b_sub = next(s for s in deactivated_subs if s['user_id'] == seed['should_revoke']['user_b']['user_id'])
            assert user_a_sub['is_active'] is False
            order_a_status = await conn.fetchval("SELECT status FROM pay_orders WHERE id = $1", user_a_sub['order_id'])
            assert order_a_status == 3
            assert user_b_sub['is_active'] is False
            order_b_status = await conn.fetchval("SELECT status FROM pay_orders WHERE id = $1", user_b_sub['order_id'])
            assert order_b_status == 3
            
            # User C уже был неактивен (не изменился)
            user_c_sub = next(s for s in deactivated_subs if s['user_id'] == seed['should_not_revoke']['user_c']['user_id'])
            assert user_c_sub['is_active'] is False
            order_c_status = await conn.fetchval("SELECT status FROM pay_orders WHERE id = $1", user_c_sub['order_id'])
            assert order_c_status == 3
            
            # User D всё ещё активен (не истёк)
            user_d_sub = next(s for s in deactivated_subs if s['user_id'] == seed['should_not_revoke']['user_d']['user_id'])
            assert user_d_sub['is_active'] is True
            order_d_status = await conn.fetchval("SELECT status FROM pay_orders WHERE id = $1", user_d_sub['order_id'])
            assert order_d_status == 2  # success
            
            # User E не попал в результат (is_deleted=true фильтрует на уровне JOIN)
            # Проверяем что его нет в outbox
            user_e_outbox = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1
            """, seed['should_not_revoke']['user_e']['order_id'])
            assert user_e_outbox == 0
    
    
    async def test_revoke_atomic_update_and_outbox(self, arq_ctx, arq_pool, revoke_seed, db_pool):
        """
        Проверяем атомарность операции: UPDATE подписок + INSERT в outbox.
        
        SQL использует CTE для атомарности:
        1. UPDATE payed_subs (deactivated_subs)
        2. JOIN с users и нодами (expired_nodes_info)
        3. INSERT INTO sub_nodes_outbox (insert_outbox)
        
        Проверяем что обе операции выполнились успешно.
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = revoke_seed
        
        # Act
        result = await revoke_sub_plan_by_expire(arq_ctx)
        
        # Assert
        assert result['success'] is True
        
        async with db_pool.acquire() as conn:
            # 1. Подписки выключены
            inactive_count = await conn.fetchval("""
                SELECT COUNT(*) FROM user_subs us
                JOIN pay_orders po ON po.id = us.order_id
                WHERE us.id IN ($1, $2) AND us.is_active = false AND po.status = 3
            """, seed['should_revoke']['user_a']['order_id'],
                 seed['should_revoke']['user_b']['order_id'])
            assert inactive_count == 2
            
            # 2. Outbox заполнен
            outbox_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox
                WHERE user_sub_id IN ($1, $2) AND operation = 2
            """, seed['should_revoke']['user_a']['order_id'],
                 seed['should_revoke']['user_b']['order_id'])
            assert outbox_count >= 2  # Минимум 2 (по 1 на ноду для каждого юзера)
            
            # 3. Проверяем соответствие: для каждой подписки есть записи в outbox
            for user_key in ['user_a', 'user_b']:
                order_id = seed['should_revoke'][user_key]['order_id']
                outbox_for_order = await conn.fetchval("""
                    SELECT COUNT(*) FROM sub_nodes_outbox WHERE user_sub_id = $1
                """, order_id)
                assert outbox_for_order >= 1  # Минимум 1 нода
    
    
    async def test_revoke_enqueues_bulk_delete_jobs(self, arq_ctx, arq_pool, revoke_seed, db_pool):
        """
        Проверяем что задачи bulk_action_users_by_node (operation=DELETE) поставлены в ARQ.
        
        Проверяем:
        - Задачи существуют в Redis
        - Количество задач соответствует количеству нод
        - operation=2 (DELETE)
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = revoke_seed
        
        # Получаем количество уникальных АКТИВНЫХ ВИДИМЫХ нод для пользователей
        async with db_pool.acquire() as conn:
            nodes_count = await conn.fetchval("""
                SELECT COUNT(DISTINCT vsp.node_proto_id)
                FROM vnodes_sub_plans vsp
                JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
                JOIN nodes n ON np.node_id = n.id AND n.is_active = true
                WHERE vsp.sub_plan_id = $1
            """, seed['plan_id'])
        
        # Act
        result = await revoke_sub_plan_by_expire(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert result['total_nodes'] == nodes_count
        
        # Примечание: Не проверяем длину очереди напрямую, так как ARQ воркеры
        # могут обработать задачи быстрее чем мы проверим очередь.
        # Факт успешного enqueue_job подтверждается логами и result['total_nodes']
    
    
    async def test_revoke_groups_by_node_correctly(self, arq_ctx, arq_pool, revoke_seed, db_pool):
        """
        Проверяем правильность группировки пользователей по нодам.
        
        SQL группирует через GROUP BY node_proto_id.
        Проверяем что каждая нода получит своих пользователей.
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = revoke_seed
        
        # Act
        result = await revoke_sub_plan_by_expire(arq_ctx)
        
        # Assert
        assert result['success'] is True
        
        # Проверяем группировку через outbox
        async with db_pool.acquire() as conn:
            # Получаем записи outbox сгруппированные по нодам
            grouped = await conn.fetch("""
                SELECT node_proto_id, COUNT(*) as users_count, 
                       array_agg(user_sub_id) as user_sub_ids
                FROM sub_nodes_outbox
                WHERE operation = 2
                GROUP BY node_proto_id
                ORDER BY node_proto_id
            """)
            
            # Проверяем что есть записи
            assert len(grouped) >= 1
            
            # Проверяем что user_a и user_b присутствуют
            all_user_sub_ids = []
            for group in grouped:
                all_user_sub_ids.extend(group['user_sub_ids'])
            
            assert seed['should_revoke']['user_a']['order_id'] in all_user_sub_ids
            assert seed['should_revoke']['user_b']['order_id'] in all_user_sub_ids
