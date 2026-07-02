"""
Integration тесты для collect_traffic_metrics — функции сбора метрик трафика с нод.

collect_traffic_metrics выполняет:
1. Параллельный сбор метрик с нод (с батчингом через semaphore)
2. Парсинг stdout через parse_node_output
3. Обновление трафика в БД через update_traffic
4. Запуск bulk_delete_by_traffic_limit для пользователей, превысивших лимит

КРИТИЧЕСКАЯ ПРОВЕРКА SQL ФИЛЬТРОВ:
Блокируются ТОЛЬКО пользователи со ВСЕМИ условиями:
- Превысили лимит трафика (traffic_used_day_mb > traffic_limit_day)
- Подписка активна (is_active = true)
- Пользователь не удалён (is_deleted = false)
- Пользователь не был ограничен ранее (is_limited = false)
"""
import pytest

from web.sub.arq_tasks.metrics_collector import collect_traffic_metrics


pytestmark = pytest.mark.asyncio


class TestCollectTrafficMetrics:
    """Integration тесты для collect_traffic_metrics"""
    
    async def test_collect_metrics_success_no_limits(self, db_pool, arq_ctx, metrics_collector_seed):
        """
        Успешный сбор метрик, никто не превышает лимит.
        
        Добавляем трафик пользователям, но они остаются в пределах лимита.
        """
        # Arrange
        seed = metrics_collector_seed
        
        # Fake aiohttp возвращает метрики с небольшим трафиком (не превышает лимит)
        fake_stdout = {
            'stat': [
                {'name': 'user>>>user_a_should_block>>>traffic>>>downlink', 'value': 52428800},  # 50MB
                {'name': 'user>>>user_b_should_block>>>traffic>>>downlink', 'value': 31457280},  # 30MB
            ]
        }
        
        arq_ctx['aio_http'] = FakeAiohttpSession(json_data={'stdout': fake_stdout}, status=200)
        
        # Получаем данные ноды из БД
        async with db_pool.acquire() as conn:
            node = await conn.fetchrow("""
                SELECT np.id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                       pt.metrics_parser_code, pt.sub_required_libs, pt.metrics_command, pt.api_metrics_script
                FROM nodes_protocols np
                JOIN nodes n ON np.node_id = n.id
                JOIN protocols p ON np.proto_id = p.id
                JOIN proto_templates pt ON p.tmp_id = pt.id
                WHERE np.id = $1
            """, seed['vnode_id'])
            
            nodes = [dict(node)]
        
        # Act
        result = await collect_traffic_metrics(arq_ctx, nodes)
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 1
        assert result['error_count'] == 0
        
        # Проверяем что трафик обновился
        async with db_pool.acquire() as conn:
            user_a = await conn.fetchrow("SELECT traffic_used_day_mb FROM users WHERE tg_username = $1", "user_a_should_block")
            user_b = await conn.fetchrow("SELECT traffic_used_day_mb FROM users WHERE tg_username = $1", "user_b_should_block")
            
            # 500 (начальный) + 50 (добавленный) = 550MB
            assert user_a['traffic_used_day_mb'] == 550
            # 800 (начальный) + 30 (добавленный) = 830MB
            assert user_b['traffic_used_day_mb'] == 830
            
            # Проверяем что user_a и user_b НЕ были ограничены (все в пределах лимита 1000MB)
            user_a_limited = await conn.fetchval(
                "SELECT is_limited FROM payed_subs WHERE id = $1", 
                seed['should_block']['user_a']['order_id']
            )
            user_b_limited = await conn.fetchval(
                "SELECT is_limited FROM payed_subs WHERE id = $1",
                seed['should_block']['user_b']['order_id']
            )
            assert user_a_limited is False
            assert user_b_limited is False
            
            # Проверяем что outbox пуст (никто не превысил лимит)
            outbox = await conn.fetch("SELECT * FROM sub_nodes_outbox WHERE operation = 2")
            assert len(outbox) == 0
    
    
    async def test_collect_metrics_with_traffic_limit_exceeded(self, db_pool, arq_ctx, arq_pool, metrics_collector_seed):
        """
        КРИТИЧЕСКИЙ ТЕСТ: Проверяем что блокируются ТОЛЬКО валидные пользователи.
        
        Добавляем трафик всем пользователям так, чтобы они превысили лимит.
        Проверяем что блокируются ТОЛЬКО user_a и user_b (остальные фильтруются).
        """
        # Arrange
        seed = metrics_collector_seed
        arq_ctx['arq_redis'] = arq_pool
        
        # Fake aiohttp возвращает большой трафик (все превышают лимит 1000MB)
        fake_stdout = {
            'stat': [
                # User A: 500 + 600 = 1100MB (превышает лимит) → ДОЛЖЕН блокироваться
                {'name': 'user>>>user_a_should_block>>>traffic>>>downlink', 'value': 629145600},  # 600MB
                # User B: 800 + 300 = 1100MB (превышает лимит) → ДОЛЖЕН блокироваться
                {'name': 'user>>>user_b_should_block>>>traffic>>>downlink', 'value': 314572800},  # 300MB
                # User C: 500 + 600 = 1100MB, но подписка неактивна → НЕ блокируется
                {'name': 'user>>>user_c_inactive_sub>>>traffic>>>downlink', 'value': 629145600},  # 600MB
                # User D: 500 + 600 = 1100MB, но пользователь удалён → НЕ блокируется
                {'name': 'user>>>user_d_deleted>>>traffic>>>downlink', 'value': 629145600},  # 600MB
                # User E: 500 + 600 = 1100MB, но уже ограничен → НЕ блокируется
                {'name': 'user>>>user_e_already_limited>>>traffic>>>downlink', 'value': 629145600},  # 600MB
                # User F: 500 + 400 = 900MB (НЕ превышает лимит) → НЕ блокируется
                {'name': 'user>>>user_f_within_limit>>>traffic>>>downlink', 'value': 419430400},  # 400MB
                # User G: 500 + 600 = 1100MB, но подписка истекла → НЕ блокируется
                {'name': 'user>>>user_g_expired_sub>>>traffic>>>downlink', 'value': 629145600},  # 600MB
            ]
        }
        
        arq_ctx['aio_http'] = FakeAiohttpSession(json_data={'stdout': fake_stdout}, status=200)
        
        # Получаем ноду
        async with db_pool.acquire() as conn:
            node = await conn.fetchrow("""
                SELECT np.id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                       pt.metrics_parser_code, pt.sub_required_libs, pt.metrics_command, pt.api_metrics_script
                FROM nodes_protocols np
                JOIN nodes n ON np.node_id = n.id
                JOIN protocols p ON np.proto_id = p.id
                JOIN proto_templates pt ON p.tmp_id = pt.id
                WHERE np.id = $1
            """, seed['vnode_id'])
            
            nodes = [dict(node)]
        
        # Act
        result = await collect_traffic_metrics(arq_ctx, nodes)
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 1
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА: В outbox должны быть ТОЛЬКО user_a и user_b
        async with db_pool.acquire() as conn:
            outbox_records = await conn.fetch("""
                SELECT order_id, user_uuid, tg_username 
                FROM sub_nodes_outbox 
                WHERE operation = 2
                ORDER BY tg_username
            """)
            
            assert len(outbox_records) == 2, f"Expected 2 records in outbox, got {len(outbox_records)}"
            
            outbox_order_ids = {r['order_id'] for r in outbox_records}
            expected_order_ids = {
                seed['should_block']['user_a']['order_id'],
                seed['should_block']['user_b']['order_id'],
            }
            assert outbox_order_ids == expected_order_ids, f"Outbox order_ids mismatch: {outbox_order_ids} != {expected_order_ids}"
            
            # Проверяем что is_limited установлен для user_a и user_b
            # (user_e уже был limited, поэтому его не учитываем в expected)
            limited_subs = await conn.fetch("""
                SELECT id FROM payed_subs 
                WHERE is_limited = true 
                  AND user_id IN (SELECT id FROM users WHERE tg_id BETWEEN 200001 AND 200002)
            """)
            limited_ids = {r['id'] for r in limited_subs}
            assert limited_ids == expected_order_ids, f"is_limited mismatch: {limited_ids} != {expected_order_ids}"
            
            # Проверяем что трафик обновился для ВСЕХ пользователей
            user_a = await conn.fetchrow("SELECT traffic_used_day_mb FROM users WHERE tg_username = $1", "user_a_should_block")
            user_b = await conn.fetchrow("SELECT traffic_used_day_mb FROM users WHERE tg_username = $1", "user_b_should_block")
            user_f = await conn.fetchrow("SELECT traffic_used_day_mb FROM users WHERE tg_username = $1", "user_f_within_limit")
            
            assert user_a['traffic_used_day_mb'] == 1100  # 500 + 600
            assert user_b['traffic_used_day_mb'] == 1100  # 800 + 300
            assert user_f['traffic_used_day_mb'] == 900   # 500 + 400 (НЕ превышает лимит)
            
            # Проверяем что bulk_delete_by_traffic_limit был вызван
            # (через проверку jobs в arq - это сложно, поэтому проверяем outbox)
            # В реальном тесте можно проверить через arq_pool.enqueue_job mock
    
    
    async def test_collect_metrics_sql_filters_verification(self, db_pool, arq_ctx, metrics_collector_seed):
        """
        Углублённая проверка всех SQL фильтров в update_traffic.
        
        Проверяем каждый фильтр отдельно:
        1. is_deleted = false
        2. is_active = true
        3. is_limited = false
        4. traffic_used_day_mb > traffic_limit_day
        """
        # Arrange
        seed = metrics_collector_seed
        
        # Добавляем трафик так, чтобы ВСЕ превысили лимит
        fake_stdout = {
            'stat': [
                {'name': f'user>>>user_a_should_block>>>traffic>>>downlink', 'value': 629145600},  # +600MB
                {'name': f'user>>>user_c_inactive_sub>>>traffic>>>downlink', 'value': 629145600},
                {'name': f'user>>>user_d_deleted>>>traffic>>>downlink', 'value': 629145600},
                {'name': f'user>>>user_e_already_limited>>>traffic>>>downlink', 'value': 629145600},
            ]
        }
        
        arq_ctx['aio_http'] = FakeAiohttpSession(json_data={'stdout': fake_stdout}, status=200)
        
        async with db_pool.acquire() as conn:
            node = await conn.fetchrow("""
                SELECT np.id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                       pt.metrics_parser_code, pt.sub_required_libs, pt.metrics_command, pt.api_metrics_script
                FROM nodes_protocols np
                JOIN nodes n ON np.node_id = n.id
                JOIN protocols p ON np.proto_id = p.id
                JOIN proto_templates pt ON p.tmp_id = pt.id
                WHERE np.id = $1
            """, seed['vnode_id'])
            
            nodes = [dict(node)]
        
        # Act
        await collect_traffic_metrics(arq_ctx, nodes)
        
        # Assert: Проверяем каждый фильтр
        async with db_pool.acquire() as conn:
            # 1. Фильтр is_deleted = false
            user_d_limited = await conn.fetchval(
                "SELECT is_limited FROM payed_subs WHERE id = $1",
                seed['should_not_block']['user_d']['order_id']
            )
            assert user_d_limited is False, "User D (deleted) should NOT be limited"
            
            # 2. Фильтр is_active = true
            user_c_limited = await conn.fetchval(
                "SELECT is_limited FROM payed_subs WHERE id = $1",
                seed['should_not_block']['user_c']['order_id']
            )
            assert user_c_limited is False, "User C (inactive sub) should NOT be limited"
            
            # 3. Фильтр is_limited = false
            user_e_outbox = await conn.fetchval(
                "SELECT COUNT(*) FROM sub_nodes_outbox WHERE order_id = $1",
                seed['should_not_block']['user_e']['order_id']
            )
            assert user_e_outbox == 0, "User E (already limited) should NOT be in outbox"
            
            # 4. Только user_a должен быть ограничен
            outbox_count = await conn.fetchval("SELECT COUNT(*) FROM sub_nodes_outbox WHERE operation = 2")
            assert outbox_count == 1, f"Expected 1 record in outbox, got {outbox_count}"
    
    
    async def test_collect_metrics_node_returns_error(self, db_pool, arq_ctx, metrics_collector_seed):
        """
        Одна нода возвращает ошибку 500, но не ломает весь процесс.
        """
        # Arrange
        seed = metrics_collector_seed
        arq_ctx['aio_http'] = FakeAiohttpSession(json_data={'error': 'Internal error'}, status=500)
        
        async with db_pool.acquire() as conn:
            node = await conn.fetchrow("""
                SELECT np.id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                       pt.metrics_parser_code, pt.sub_required_libs, pt.metrics_command, pt.api_metrics_script
                FROM nodes_protocols np
                JOIN nodes n ON np.node_id = n.id
                JOIN protocols p ON np.proto_id = p.id
                JOIN proto_templates pt ON p.tmp_id = pt.id
                WHERE np.id = $1
            """, seed['vnode_id'])
            
            nodes = [dict(node)]
        
        # Act
        result = await collect_traffic_metrics(arq_ctx, nodes)
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 0
        assert result['error_count'] == 1
        
        # Трафик НЕ обновился
        async with db_pool.acquire() as conn:
            user_a = await conn.fetchrow("SELECT traffic_used_day_mb FROM users WHERE tg_username = $1", "user_a_should_block")
            assert user_a['traffic_used_day_mb'] == 500  # Начальное значение не изменилось
    
    
    async def test_collect_metrics_empty_stdout(self, db_pool, arq_ctx, metrics_collector_seed):
        """
        Нода возвращает пустые метрики (нет данных).
        """
        # Arrange
        seed = metrics_collector_seed
        fake_stdout = {'stat': []}  # Пустой список
        arq_ctx['aio_http'] = FakeAiohttpSession(json_data={'stdout': fake_stdout}, status=200)
        
        async with db_pool.acquire() as conn:
            node = await conn.fetchrow("""
                SELECT np.id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                       pt.metrics_parser_code, pt.sub_required_libs, pt.metrics_command, pt.api_metrics_script
                FROM nodes_protocols np
                JOIN nodes n ON np.node_id = n.id
                JOIN protocols p ON np.proto_id = p.id
                JOIN proto_templates pt ON p.tmp_id = pt.id
                WHERE np.id = $1
            """, seed['vnode_id'])
            
            nodes = [dict(node)]
        
        # Act
        result = await collect_traffic_metrics(arq_ctx, nodes)
        
        # Assert
        assert result['success'] is True
        assert result['success_count'] == 0  # Нет данных для обновления
        
        # Трафик НЕ обновился (нет данных)
        async with db_pool.acquire() as conn:
            user_a = await conn.fetchrow("SELECT traffic_used_day_mb FROM users WHERE tg_username = $1", "user_a_should_block")
            assert user_a['traffic_used_day_mb'] == 500
    
    
    async def test_collect_metrics_no_nodes(self, arq_ctx):
        """
        Edge case: пустой список нод.
        """
        # Act
        result = await collect_traffic_metrics(arq_ctx, [])
        
        # Assert
        assert result['success'] is True
        assert result['nodes_total'] == 0
        assert result['success_count'] == 0
        assert result['error_count'] == 0


# Импортируем FakeAiohttpSession из conftest
from web.sub.tests.conftest import FakeAiohttpSession
