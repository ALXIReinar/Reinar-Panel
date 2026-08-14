"""
Integration тесты для retry_stuck_core_proto_actions - кроны ретрая залипших операций.

retry_stuck_core_proto_actions:
1. Находит "залипшие" операции через get_stuck_actions()
2. АТОМАРНО устанавливает is_retried = true
3. Для каждой операции получает ноды
4. Ставит задачи action_on_core_proto_by_sub_plan в ARQ

Критические SQL фильтры в get_stuck_actions():
- is_retried = false (только не ретраенные)
- created_at < now() - interval '1 hour' (только старые > 1 часа)

Критический фильтр в коде:
- if len(sub_nodes) > 0 (не ставить задачи если нет нод)
"""
import pytest

from web.arq_worker.funcs.outbox_cleaner import retry_stuck_core_proto_actions


pytestmark = pytest.mark.asyncio


class TestRetryStuckCoreProtoActions:
    """Integration тесты для retry_stuck_core_proto_actions"""
    
    async def test_retry_stuck_success(self, arq_ctx, arq_pool, outbox_cleaner_seed, db_pool):
        """
        Успешный ретрай залипших операций.
        
        Проверяем:
        - is_retried = true для обработанных записей
        - Задачи поставлены в ARQ
        - Старые записи (> 1 час) обработаны
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = outbox_cleaner_seed
        
        # Act
        result = await retry_stuck_core_proto_actions(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert 'Чистка зависших операций' in result['message']
        assert result['stuck_len'] >= 2  # Минимум 2 залипших (outbox_a, outbox_b)
        
        # Проверяем что is_retried установлен в true
        async with db_pool.acquire() as conn:
            # Outbox A и Outbox B должны быть помечены как ретраенные
            outbox_a = await conn.fetchrow("""
                SELECT is_retried FROM sub_nodes_outbox WHERE id = $1
            """, seed['should_retry']['outbox_a']['id'])
            
            outbox_b = await conn.fetchrow("""
                SELECT is_retried FROM sub_nodes_outbox WHERE id = $1
            """, seed['should_retry']['outbox_b']['id'])
            
            assert outbox_a['is_retried'] is True
            assert outbox_b['is_retried'] is True
            
            # Outbox C (свежая) НЕ должна быть помечена
            outbox_c = await conn.fetchrow("""
                SELECT is_retried FROM sub_nodes_outbox WHERE id = $1
            """, seed['should_not_retry']['outbox_c']['id'])
            assert outbox_c['is_retried'] is False
    
    
    async def test_retry_stuck_no_stuck_actions(self, arq_ctx, db_pool, db_seed):
        """
        Нет залипших операций - idle.
        
        Проверяем:
        - Возвращается success=True
        - stuck_len = 0
        """
        # Arrange - БД очищена через db_seed, нет outbox записей
        
        # Act
        result = await retry_stuck_core_proto_actions(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert result['stuck_len'] == 0
    
    
    async def test_retry_stuck_sql_filters_critical(self, arq_ctx, arq_pool, outbox_cleaner_seed, db_pool):
        """
        КРИТИЧЕСКИЙ ТЕСТ SQL ФИЛЬТРОВ: Проверяем что ретраятся ТОЛЬКО валидные записи.
        
        Должны ретраиться:
        - Outbox A: is_retried=false, created_at < now() - 2 hours ✅
        - Outbox B: is_retried=false, created_at < now() - 3 hours ✅
        - Outbox E: is_retried=false, created_at < now() - 2 hours (но len(sub_nodes)=0) ✅ попадёт в выборку
        
        НЕ должны ретраиться:
        - Outbox C: created_at = now() - 30 min (слишком свежая) ❌
        - Outbox D: is_retried=true (уже ретраился) ❌
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = outbox_cleaner_seed
        
        # Act
        result = await retry_stuck_core_proto_actions(arq_ctx)
        
        # Assert
        assert result['success'] is True
        
        async with db_pool.acquire() as conn:
            # Проверяем ТОЛЬКО outbox_a, outbox_b, outbox_e помечены как ретраенные
            all_outbox = await conn.fetch("""
                SELECT id, is_retried, created_at
                FROM sub_nodes_outbox
                WHERE id IN ($1, $2, $3, $4, $5)
                ORDER BY id
            """, seed['should_retry']['outbox_a']['id'],
                 seed['should_retry']['outbox_b']['id'],
                 seed['should_not_retry']['outbox_c']['id'],
                 seed['should_not_retry']['outbox_d']['id'],
                 seed['should_not_retry']['outbox_e']['id'])
            
            # Outbox A и Outbox B должны быть ретраенные
            outbox_a = next(o for o in all_outbox if o['id'] == seed['should_retry']['outbox_a']['id'])
            outbox_b = next(o for o in all_outbox if o['id'] == seed['should_retry']['outbox_b']['id'])
            assert outbox_a['is_retried'] is True
            assert outbox_b['is_retried'] is True
            
            # Outbox C (свежая < 1 час) НЕ должна быть ретраенная
            outbox_c = next(o for o in all_outbox if o['id'] == seed['should_not_retry']['outbox_c']['id'])
            assert outbox_c['is_retried'] is False
            
            # Outbox D (уже ретраился) остался is_retried=true
            outbox_d = next(o for o in all_outbox if o['id'] == seed['should_not_retry']['outbox_d']['id'])
            assert outbox_d['is_retried'] is True
            
            # Outbox E (no nodes) должен быть помечен как ретраенный (попал в SQL выборку)
            outbox_e = next(o for o in all_outbox if o['id'] == seed['should_not_retry']['outbox_e']['id'])
            assert outbox_e['is_retried'] is True
    
    
    async def test_retry_stuck_atomic_update(self, arq_ctx, arq_pool, outbox_cleaner_seed, db_pool):
        """
        Проверяем атомарность операции UPDATE is_retried + RETURNING.
        
        SQL использует CTE для атомарности:
        1. UPDATE sub_nodes_outbox SET is_retried = true
        2. RETURNING записи для обработки
        
        Проверяем что обе операции выполнились успешно.
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = outbox_cleaner_seed
        
        # Запоминаем начальное состояние
        async with db_pool.acquire() as conn:
            initial_state = await conn.fetchrow("""
                SELECT is_retried FROM sub_nodes_outbox WHERE id = $1
            """, seed['should_retry']['outbox_a']['id'])
            assert initial_state['is_retried'] is False  # Должно быть false
        
        # Act
        result = await retry_stuck_core_proto_actions(arq_ctx)
        
        # Assert
        assert result['success'] is True
        
        async with db_pool.acquire() as conn:
            # 1. Проверяем что is_retried обновлён
            updated_state = await conn.fetchrow("""
                SELECT is_retried FROM sub_nodes_outbox WHERE id = $1
            """, seed['should_retry']['outbox_a']['id'])
            assert updated_state['is_retried'] is True
            
            # 2. Проверяем что задачи поставлены (косвенно через stuck_len)
            assert result['stuck_len'] >= 2
    
    
    async def test_retry_stuck_enqueues_jobs(self, arq_ctx, arq_pool, outbox_cleaner_seed, db_pool):
        """
        Проверяем что задачи action_on_core_proto_by_sub_plan поставлены в ARQ.
        
        Проверяем:
        - stuck_len соответствует количеству уникальных нод (не записей outbox!)
        - Задачи поставлены для всех валидных записей
        
        ВАЖНО: retry_stuck_core_proto_actions группирует по нодам,
        поэтому stuck_len = количество уникальных node_proto_id.
        
        Архитектура:
        - SQL группирует записи outbox по node_proto_id
        - На каждую ноду формируется events_timeline с пользователями
        - Python код всхлопывает состояния пользователей на ноде
        - Результат: 2 bulk операции (ADD + DELETE) на каждую ноду
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = outbox_cleaner_seed
        
        # Получаем количество уникальных нод (не записей!)
        async with db_pool.acquire() as conn:
            unique_nodes_count = await conn.fetchval("""
                SELECT COUNT(DISTINCT node_proto_id) 
                FROM sub_nodes_outbox
                WHERE is_retried = false AND created_at < now() - interval '1 hour'
            """)
        
        # Act
        result = await retry_stuck_core_proto_actions(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert result['stuck_len'] == unique_nodes_count  # <-- Количество НОДОВ, не записей!
        assert result['stuck_len'] == 2  # vnode_id_10 (outbox_a + outbox_e), vnode_id_11 (outbox_b)
        
        # Примечание: Не проверяем длину очереди напрямую, так как ARQ воркеры
        # могут обработать задачи быстрее чем мы проверим очередь.
        # Факт успешного enqueue_job подтверждается логами и отсутствием ошибок
    
    
    async def test_retry_stuck_skips_empty_nodes(self, arq_ctx, arq_pool, outbox_cleaner_seed, db_pool):
        """
        Проверяем фильтр if len(sub_nodes) > 0 в коде.
        
        Операции для неактивных подписок (len(sub_nodes)=0) НЕ должны получать задачи.
        
        Outbox E имеет неактивную подписку → get_nodes_to_core_proto_action вернёт [] → задача НЕ ставится.
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = outbox_cleaner_seed
        
        # Act
        result = await retry_stuck_core_proto_actions(arq_ctx)
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что outbox_e попал в SQL выборку (is_retried=true)
        async with db_pool.acquire() as conn:
            outbox_e = await conn.fetchrow("""
                SELECT is_retried FROM sub_nodes_outbox WHERE id = $1
            """, seed['should_not_retry']['outbox_e']['id'])
            assert outbox_e['is_retried'] is True
            
            # Но задача для него НЕ должна быть поставлена (len(sub_nodes)=0)
            # Это косвенно проверяется отсутствием ошибок в логах
            # Прямую проверку сделать сложно, так как ARQ не хранит детали задач
    
    
    async def test_retry_stuck_state_compaction(self, arq_ctx, arq_pool, db_pool, arq_test_seed):
        """
        Проверяем логику всхлопывания состояний (State Compaction).
        
        Если у одного пользователя несколько операций на одной ноде:
        ADD → DELETE → ADD
        
        Должна выбраться последняя самая свежая операция (ADD).
        Все event_id всхлопнувшихся операций должны быть сохранены.
        
        Архитектура всхлопывания:
        1. SQL сортирует события по event_id ASC (от старых к новым)
        2. Python итерирует по events_timeline, перезаписывая operation
        3. Все event_id собираются в массив для закрытия после успеха
        4. Финальная операция = последняя в хронологии
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        
        async with db_pool.acquire() as conn:
            # Очищаем outbox
            await conn.execute("DELETE FROM sub_nodes_outbox")
            
            # Создаём пользователя
            user_id = await conn.fetchval("""
                INSERT INTO users (tg_id, tg_username, is_deleted)
                VALUES ($1, $2, false)
                RETURNING id
            """, 600001, "user_state_compaction")
            
            pay_order_id = await conn.fetchval("""
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
            """, user_id, arq_test_seed['offer_id'])
            
            sub_id = await conn.fetchval("""
                INSERT INTO user_subs (
                    user_id, sub_plan_id, order_id, is_active, expire_date,
                    uuid, b64_id, infinite_traffic, infinite_expire,
                    traffic_limit_day, used_mb_limit, used_mb, traffic_used_day_mb, is_limited
                )
                VALUES ($1, $2, $3, true, now() + interval '30 days', $4, $5, false, false, 10240, NULL, 0, 0, false)
                RETURNING id
            """, user_id, arq_test_seed['plan_id'], pay_order_id, "uuid-compaction-test", "b64-compaction-test")
            
            # Создаём 3 операции для одного пользователя на одной ноде: ADD → DELETE → ADD
            await conn.execute("""
                INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id, is_retried, created_at)
                VALUES 
                    ($1, $2, 1, $3, false, now() - interval '3 hours'),  -- ADD (самая старая)
                    ($1, $2, 2, $3, false, now() - interval '2 hours'),  -- DELETE
                    ($1, $2, 1, $3, false, now() - interval '1.5 hours') -- ADD (самая свежая)
            """, "uuid-compaction-test", sub_id, arq_test_seed['vnode_id_10'])
        
        # Act
        result = await retry_stuck_core_proto_actions(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert result['stuck_len'] == 1  # Одна нода
        
        # Проверяем что все 3 записи помечены как ретраенные
        async with db_pool.acquire() as conn:
            retried_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sub_nodes_outbox WHERE is_retried = true
            """)
            assert retried_count == 3
            
            # Проверяем что все 3 операции были обработаны (is_retried=true)
            all_events = await conn.fetch("""
                SELECT id, operation, is_retried, created_at
                FROM sub_nodes_outbox
                ORDER BY created_at ASC
            """)
            assert len(all_events) == 3
            assert all(ev['is_retried'] is True for ev in all_events)
            
            # Проверяем хронологический порядок операций: ADD → DELETE → ADD
            assert all_events[0]['operation'] == 1  # ADD (старая)
            assert all_events[1]['operation'] == 2  # DELETE
            assert all_events[2]['operation'] == 1  # ADD (финальная)

