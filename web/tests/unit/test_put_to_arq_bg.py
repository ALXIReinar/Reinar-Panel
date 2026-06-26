"""
Unit-тесты для web.api.users.handlers.put_to_arq_bg
Проверяют правильность маппинга действий и вызовов ARQ
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from web.api.users.handlers import put_to_arq_bg


class TestPutToArqBgActionMapping:
    """Тесты маппинга действий в ARQ задачи"""
    
    @pytest.mark.asyncio
    async def test_activate_maps_to_add(self):
        """'activate' превращается в action='add' для ARQ"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-activate-123"
        mock_arq.enqueue_job.return_value = mock_job
        
        users = [
            {"order_id": 1, "sub_plan_id": 1, "user_id": 1},
            {"order_id": 2, "sub_plan_id": 1, "user_id": 2}
        ]
        
        job_id = await put_to_arq_bg(mock_arq, users, "activate")
        
        # Проверяем что вызвался правильный метод
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        # Первый аргумент - название задачи
        assert call_args[0][0] == "admin_request_bulk_action_users"
        # Второй аргумент - action='add'
        assert call_args[0][1] == "add"
        # Третий аргумент - массив пользователей
        assert call_args[0][2] == users
        
        # Проверяем что вернулся job_id
        assert job_id == "job-activate-123"
    
    @pytest.mark.asyncio
    async def test_deactivate_maps_to_delete(self):
        """'deactivate' превращается в action='delete' для ARQ"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-deactivate-456"
        mock_arq.enqueue_job.return_value = mock_job
        
        users = [
            {"order_id": 3, "sub_plan_id": 2, "user_id": 3},
        ]
        
        job_id = await put_to_arq_bg(mock_arq, users, "deactivate")
        
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        assert call_args[0][0] == "admin_request_bulk_action_users"
        assert call_args[0][1] == "delete"  # deactivate → delete
        assert call_args[0][2] == users
        assert job_id == "job-deactivate-456"
    
    @pytest.mark.asyncio
    async def test_add_stays_add(self):
        """'add' остаётся action='add' для ARQ"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-add-789"
        mock_arq.enqueue_job.return_value = mock_job
        
        users = [{"order_id": 4, "sub_plan_id": 1, "user_id": 4}]
        
        job_id = await put_to_arq_bg(mock_arq, users, "add")
        
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][0] == "admin_request_bulk_action_users"
        assert call_args[0][1] == "add"
        assert job_id == "job-add-789"
    
    @pytest.mark.asyncio
    async def test_delete_stays_delete(self):
        """'delete' остаётся action='delete' для ARQ"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-delete-101"
        mock_arq.enqueue_job.return_value = mock_job
        
        users = [{"order_id": 5, "sub_plan_id": 2, "user_id": 5}]
        
        job_id = await put_to_arq_bg(mock_arq, users, "delete")
        
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][0] == "admin_request_bulk_action_users"
        assert call_args[0][1] == "delete"
        assert job_id == "job-delete-101"


class TestPutToArqBgResetTraffic:
    """Тесты для reset_traffic - использует другую ARQ задачу"""
    
    @pytest.mark.asyncio
    async def test_reset_traffic_uses_correct_task(self):
        """'reset_traffic' вызывает reset_day_user_traffic"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-reset-202"
        mock_arq.enqueue_job.return_value = mock_job
        
        users = [
            {"order_id": 6, "sub_plan_id": 1, "user_id": 6},
            {"order_id": 7, "sub_plan_id": 1, "user_id": 7}
        ]
        
        job_id = await put_to_arq_bg(mock_arq, users, "reset_traffic")
        
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        # Для reset_traffic вызывается другая задача
        assert call_args[0][0] == "reset_day_user_traffic"
        # Первый аргумент - массив пользователей (без action)
        assert call_args[0][1] == users
        assert job_id == "job-reset-202"
    
    @pytest.mark.asyncio
    async def test_reset_traffic_with_empty_users(self):
        """reset_traffic с пустым массивом пользователей"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-reset-empty"
        mock_arq.enqueue_job.return_value = mock_job
        
        users = []
        
        job_id = await put_to_arq_bg(mock_arq, users, "reset_traffic")
        
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][0] == "reset_day_user_traffic"
        assert call_args[0][1] == []
        assert job_id == "job-reset-empty"


class TestPutToArqBgParameterOrder:
    """Тесты проверки порядка параметров в вызовах ARQ"""
    
    @pytest.mark.asyncio
    async def test_admin_request_bulk_action_users_parameter_order(self):
        """Параметры передаются в правильном порядке: task_name, action, users"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-order-test"
        mock_arq.enqueue_job.return_value = mock_job
        
        users = [{"order_id": 8, "sub_plan_id": 3, "user_id": 8}]
        
        await put_to_arq_bg(mock_arq, users, "activate")
        
        # Проверяем что позиционные аргументы переданы в правильном порядке
        call_args = mock_arq.enqueue_job.call_args[0]
        assert len(call_args) == 3
        assert call_args[0] == "admin_request_bulk_action_users"  # task_name
        assert call_args[1] == "add"  # action
        assert call_args[2] == users  # users list
    
    @pytest.mark.asyncio
    async def test_reset_day_user_traffic_parameter_order(self):
        """reset_day_user_traffic получает только users (без action)"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-reset-order"
        mock_arq.enqueue_job.return_value = mock_job
        
        users = [{"order_id": 9, "sub_plan_id": 1, "user_id": 9}]
        
        await put_to_arq_bg(mock_arq, users, "reset_traffic")
        
        # Проверяем что передан только task_name и users
        call_args = mock_arq.enqueue_job.call_args[0]
        assert len(call_args) == 2
        assert call_args[0] == "reset_day_user_traffic"  # task_name
        assert call_args[1] == users  # users list (без action!)
    
    @pytest.mark.asyncio
    async def test_users_data_structure(self):
        """Проверяем что структура данных пользователей сохраняется"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-structure-test"
        mock_arq.enqueue_job.return_value = mock_job
        
        # Используем реалистичные данные
        users = [
            {"order_id": 10, "sub_plan_id": 2, "user_id": 10},
            {"order_id": 11, "sub_plan_id": 3, "user_id": 11},
            {"order_id": 12, "sub_plan_id": 2, "user_id": 12}
        ]
        
        await put_to_arq_bg(mock_arq, users, "deactivate")
        
        # Проверяем что данные пользователей не изменились
        call_args = mock_arq.enqueue_job.call_args[0]
        passed_users = call_args[2]
        
        assert passed_users == users
        assert len(passed_users) == 3
        # Проверяем что все поля на месте
        for user in passed_users:
            assert "order_id" in user
            assert "sub_plan_id" in user
            assert "user_id" in user
