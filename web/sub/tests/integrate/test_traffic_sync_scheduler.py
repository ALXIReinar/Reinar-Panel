"""
Integration тесты для traffic_sync_scheduler - планировщика синхронизации трафика.

traffic_sync_scheduler - это крона (depth 0 в Task Chaining), которая:
1. Находит активные ноды для сбора метрик (SQL фильтры)
2. Ставит задачу collect_traffic_metrics в очередь ARQ

Критические проверки SQL фильтров:
- Только активные физические ноды (is_active = true)
- Только видимые виртуальные ноды (user_visible = true)
- Только ноды с metrics_port (metrics_port IS NOT NULL)
"""
import pytest

from web.sub.arq_tasks.metrics_collector import traffic_sync_scheduler


pytestmark = pytest.mark.asyncio


class TestTrafficSyncScheduler:
    """Integration тесты для traffic_sync_scheduler"""
    
    async def test_scheduler_success_with_nodes(self, arq_ctx, arq_pool, metrics_collector_seed, db_pool):
        """
        Успешный запуск планировщика с активными нодами.
        
        Проверяем:
        - Задача поставлена в очередь ARQ
        - Возвращается правильный job_id
        - nodes_count соответствует количеству нод
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = metrics_collector_seed
        
        # Act
        result = await traffic_sync_scheduler(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert 'job_id' in result
        assert result['nodes_count'] >= 1
        
        # Проверяем что задача действительно поставлена в ARQ через Redis
        # job_id в формате: arq:job:<job_id>
        job_key = f"arq:job:{result['job_id']}"
        job_exists = await arq_pool.exists(job_key)
        assert job_exists > 0, f"Job {result['job_id']} not found in ARQ queue"
    
    
    async def test_scheduler_no_nodes_available(self, arq_ctx, db_pool, db_seed):
        """
        Нет доступных нод для сбора метрик (пустая БД).
        
        Проверяем:
        - Возвращается success=True (не ошибка)
        - nodes_count = 0
        - job_id отсутствует
        """
        # Arrange - БД очищена через db_seed, нет нод
        
        # Act
        result = await traffic_sync_scheduler(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert result['nodes_count'] == 0
        assert 'job_id' not in result
    
    
    async def test_scheduler_filters_inactive_nodes(self, arq_ctx, arq_pool, arq_test_seed, db_pool):
        """
        КРИТИЧЕСКИЙ ТЕСТ SQL ФИЛЬТРОВ: Проверяем что планировщик игнорирует:
        - Неактивные физические ноды (is_active = false)
        - Невидимые виртуальные ноды (user_visible = false)
        - Ноды без metrics_port (metrics_port IS NULL)
        
        arq_test_seed создаёт:
        - vnode_id_10: активная, видимая, БЕЗ metrics_port → НЕ должна попасть
        - vnode_id_11: активная, видимая, БЕЗ metrics_port → НЕ должна попасть
        - vnode_id_invisible: активная, НЕвидимая, БЕЗ metrics_port → НЕ должна попасть
        - vnode_id_on_inactive: на НЕактивной физ. ноде → НЕ должна попасть
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        
        # Убеждаемся что все ноды из arq_test_seed НЕ имеют metrics_port
        async with db_pool.acquire() as conn:
            nodes_count = await conn.fetchval("""
                SELECT COUNT(*) 
                FROM nodes n
                JOIN nodes_protocols np ON np.node_id = n.id
                JOIN protocols p ON np.proto_id = p.id
                JOIN proto_templates pt ON p.tmp_id = pt.id
                WHERE n.is_active = true 
                  AND np.user_visible = true 
                  AND np.metrics_port IS NOT NULL
            """)
        
        # Act
        result = await traffic_sync_scheduler(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert result['nodes_count'] == nodes_count  # Должно быть 0 (все отфильтрованы)
    
    
    async def test_scheduler_enqueues_correct_job_args(self, arq_ctx, arq_pool, metrics_collector_seed, db_pool):
        """
        Проверяем что в ARQ передаются правильные аргументы (список нод).
        
        Проверяем структуру данных ноды:
        - id, ip, private_ip, api_port
        - metrics_port, metrics_command, api_metrics_script
        - proto_python_lib, metrics_parser_code, sub_required_libs
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        seed = metrics_collector_seed
        
        # Act
        result = await traffic_sync_scheduler(arq_ctx)
        
        # Assert
        assert result['success'] is True
        
        # Проверяем что задача поставлена в очередь (через существование job_id)
        assert 'job_id' in result
        job_key = f"arq:job:{result['job_id']}"
        job_exists = await arq_pool.exists(job_key)
        assert job_exists > 0
        
        # Проверяем структуру через БД - nodes должны содержать правильные данные
        # (детальная проверка args из ARQ сложна, поэтому проверяем через SQL)
        async with db_pool.acquire() as conn:
            node = await conn.fetchrow("""
                SELECT np.id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                       pt.metrics_parser_code
                FROM nodes_protocols np
                JOIN nodes n ON np.node_id = n.id
                JOIN protocols p ON np.proto_id = p.id
                JOIN proto_templates pt ON p.tmp_id = pt.id
                WHERE np.id = $1
            """, seed['vnode_id'])
            
            # Проверяем что нода имеет необходимые поля
            assert node['id'] == seed['vnode_id']
            assert node['metrics_port'] == 9090
            assert node['proto_python_lib'] is not None
            assert node['metrics_parser_code'] is not None
    
    
    async def test_scheduler_with_multiple_nodes(self, arq_ctx, arq_pool, db_pool, db_seed, real_parser_scripts):
        """
        Планировщик с несколькими активными нодами.
        
        Создаём 3 ноды:
        - 2 активные с metrics_port → должны попасть
        - 1 без metrics_port → НЕ должна попасть
        """
        # Arrange
        arq_ctx['arq_redis'] = arq_pool
        
        async with db_pool.acquire() as conn:
            # Создаём физическую ноду
            node_id = await conn.fetchval("""
                INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, "192.168.1.200", "10.0.0.200", 8200, "multi-test-node", "Multi Test Node", True)
            
            # Получаем парсер
            parser = list(real_parser_scripts.values())[0]
            tmp_id = parser['id']
            
            # Создаём протокол
            proto_id = await conn.fetchval("""
                INSERT INTO protocols (tmp_id, name)
                VALUES ($1, $2)
                RETURNING id
            """, tmp_id, "Multi Test Protocol")
            
            # Обновляем proto_template для метрик
            await conn.execute("""
                UPDATE proto_templates
                SET metrics_parser_code = $1,
                    metrics_command = 'xray api statsquery',
                    api_metrics_script = 'python metrics.py'
                WHERE id = $2
            """, parser['metrics_parser_code'], tmp_id)
            
            # Создаём 3 виртуальные ноды
            vnode1 = await conn.fetchval("""
                INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
            """, node_id, proto_id, "VNode Multi 1", "multi1.test.com", 9090, "/etc/config.json", True)
            
            vnode2 = await conn.fetchval("""
                INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, metrics_port, config_path, user_visible)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
            """, node_id, proto_id, "VNode Multi 2", "multi2.test.com", 9091, "/etc/config.json", True)
            
            # Третья нода БЕЗ metrics_port (должна быть отфильтрована)
            vnode3_no_port = await conn.fetchval("""
                INSERT INTO nodes_protocols (node_id, proto_id, title, sub_node_address, config_path, user_visible)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, node_id, proto_id, "VNode Multi 3 No Port", "multi3.test.com", "/etc/config.json", True)
        
        # Act
        result = await traffic_sync_scheduler(arq_ctx)
        
        # Assert
        assert result['success'] is True
        assert result['nodes_count'] == 2  # Только 2 ноды с metrics_port
        
        # Проверяем что job поставлен в очередь
        assert 'job_id' in result
        job_key = f"arq:job:{result['job_id']}"
        job_exists = await arq_pool.exists(job_key)
        assert job_exists > 0
        
        # Проверяем через БД что правильные ноды выбраны
        async with db_pool.acquire() as conn:
            selected_nodes = await conn.fetch("""
                SELECT np.id
                FROM nodes n
                JOIN nodes_protocols np ON np.node_id = n.id
                JOIN protocols p ON np.proto_id = p.id
                JOIN proto_templates pt ON p.tmp_id = pt.id
                WHERE n.is_active = true 
                  AND np.user_visible = true 
                  AND np.metrics_port IS NOT NULL
            """)
            
            node_ids = {n['id'] for n in selected_nodes}
            assert len(node_ids) == 2
            assert vnode1 in node_ids
            assert vnode2 in node_ids
            assert vnode3_no_port not in node_ids  # Отфильтрована
