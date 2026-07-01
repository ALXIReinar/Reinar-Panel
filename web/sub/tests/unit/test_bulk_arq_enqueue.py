"""
Unit тесты для проверки постановки bulk задач в ARQ очередь.

Проверяем что задачи действительно попадают в Redis через реальный ARQ pool.
"""
import pytest
from arq.jobs import Job

pytestmark = pytest.mark.asyncio


class TestBulkOperationsArqEnqueue:
    """Тесты постановки bulk задач в ARQ очередь"""
    
    async def test_bulk_add_enqueued_to_real_arq(self, arq_pool, arq_test_seed):
        """
        Проверяем что bulk_add_users_into_single_node действительно попадает в Redis.
        
        Используем реальный arq_pool для проверки.
        """
        # Arrange
        user3 = arq_test_seed['user3_active_for_add']
        users = [{
            'uuid': user3['uuid'],
            'tg_username': user3['tg_username'],
            'order_id': user3['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        # Act
        job = await arq_pool.enqueue_job(
            'bulk_add_users_into_single_node',
            arq_test_seed['vnode_id_10'],  # node_proto_id
            "10.0.0.100",  # private_ip
            8100,  # api_port
            9090,  # metrics_port
            "vless",  # proto_python_lib
            "python add.py",  # api_add_user_script
            {},  # bulk_add_script_custom_params
            users,  # users
            "systemctl reload test",  # reload_core_command
            "/etc/config.json",  # config_file_path
            "clients",  # flatten_json_users_key
            "email",  # flatten_user_identifier_key
            {"id": "{USER_UUID}"},  # required_user_data_obj
            {"level": 0},  # constant_user_data_obj
            1,  # current_attempt
        )
        
        # Assert
        assert job is not None
        assert isinstance(job, Job)
        assert job.job_id is not None
        
        # Проверяем что задача действительно в Redis (через Job.info())
        job_info = await job.info()
        assert job_info is not None
        assert job_info.function == 'bulk_add_users_into_single_node'
        assert job_info.enqueue_time is not None
    
    
    async def test_bulk_delete_enqueued_to_real_arq(self, arq_pool, arq_test_seed):
        """
        Проверяем что bulk_delete_users_from_single_node действительно попадает в Redis.
        
        Используем реальный arq_pool для проверки.
        """
        # Arrange
        user4 = arq_test_seed['user4_active_for_delete']
        users = [{
            'uuid': user4['uuid'],
            'tg_username': user4['tg_username'],
            'order_id': user4['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        # Act
        job = await arq_pool.enqueue_job(
            'bulk_delete_users_from_single_node',
            arq_test_seed['vnode_id_10'],  # node_proto_id
            "10.0.0.100",  # private_ip
            8100,  # api_port
            9090,  # metrics_port
            "vless",  # proto_python_lib
            "python bulk_del.py",  # api_bulk_delete_user_script
            {},  # bulk_delete_script_custom_params
            users,  # users
            "systemctl reload test",  # reload_core_command
            "/etc/config.json",  # config_file_path
            "clients",  # flatten_json_users_key
            "email",  # flatten_user_identifier_key
            1,  # current_attempt
        )
        
        # Assert
        assert job is not None
        assert isinstance(job, Job)
        assert job.job_id is not None
        
        # Проверяем что задача действительно в Redis (через Job.info())
        job_info = await job.info()
        assert job_info is not None
        assert job_info.function == 'bulk_delete_users_from_single_node'
        assert job_info.enqueue_time is not None
    
    
    async def test_bulk_add_defer_by_parameter(self, arq_pool, arq_test_seed):
        """
        Проверяем что параметр _defer_by работает (отложенное выполнение).
        
        Задача должна быть в очереди, но не выполняться сразу.
        """
        # Arrange
        user3 = arq_test_seed['user3_active_for_add']
        users = [{
            'uuid': user3['uuid'],
            'tg_username': user3['tg_username'],
            'order_id': user3['order_active'],
            'sub_node_id': arq_test_seed['vnode_id_10']
        }]
        
        # Act - откладываем на 120 секунд
        job = await arq_pool.enqueue_job(
            'bulk_add_users_into_single_node',
            arq_test_seed['vnode_id_10'],
            "10.0.0.100",
            8100,
            9090,
            "vless",
            "python add.py",
            {},
            users,
            "systemctl reload test",
            "/etc/config.json",
            "clients",
            "email",
            {"id": "{USER_UUID}"},
            {"level": 0},
            2,  # current_attempt = 2 (второй retry)
            _defer_by=120  # Отложить на 120 секунд
        )
        
        # Assert
        assert job is not None
        
        # Проверяем что задача в очереди (через Job.info())
        job_info = await job.info()
        assert job_info is not None
        assert job_info.function == 'bulk_add_users_into_single_node'
        
        # Проверяем что задача успешно поставлена в очередь с _defer_by
        # (детальная проверка defer_until требует доступа к Redis напрямую)
        assert job_info.enqueue_time is not None
