"""
Unit-тесты для web.api.users.handlers.put_to_arq_bg_bulk
Проверяют правильность маппинга действий и вызовов ARQ
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from web.api.users.handlers import put_to_arq_bg_bulk


class TestPutToArqBgActionMapping:
    """Тесты маппинга действий в ARQ задачи"""
    
    @pytest.mark.asyncio
    async def test_activate_maps_to_add(self):
        """'activate' превращается в action='add' для ARQ и передаёт event_ids"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-activate-123"
        mock_arq.enqueue_job.return_value = mock_job
        
        event_ids = [101, 102]
        
        job_id = await put_to_arq_bg_bulk(mock_arq, event_ids, "activate")
        
        # Проверяем что вызвался правильный метод
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        # Первый аргумент - название задачи
        assert call_args[0][0] == "admin_request_bulk_action_users"
        # Второй аргумент - action='add'
        assert call_args[0][1] == "add"
        # Третий аргумент - массив event_ids
        assert call_args[0][2] == event_ids
        
        # Проверяем что вернулся job_id
        assert job_id == "job-activate-123"
    
    @pytest.mark.asyncio
    async def test_deactivate_maps_to_delete(self):
        """'deactivate' превращается в action='delete' для ARQ и передаёт event_ids"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-deactivate-456"
        mock_arq.enqueue_job.return_value = mock_job
        
        event_ids = [201]
        
        job_id = await put_to_arq_bg_bulk(mock_arq, event_ids, "deactivate")
        
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        assert call_args[0][0] == "admin_request_bulk_action_users"
        assert call_args[0][1] == "delete"  # deactivate → delete
        assert call_args[0][2] == event_ids
        assert job_id == "job-deactivate-456"
    
    @pytest.mark.asyncio
    async def test_add_stays_add(self):
        """'add' остаётся action='add' для ARQ и передаёт event_ids"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-add-789"
        mock_arq.enqueue_job.return_value = mock_job
        
        event_ids = [301, 302, 303]
        
        job_id = await put_to_arq_bg_bulk(mock_arq, event_ids, "add")
        
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][0] == "admin_request_bulk_action_users"
        assert call_args[0][1] == "add"
        assert call_args[0][2] == event_ids
        assert job_id == "job-add-789"
    
    @pytest.mark.asyncio
    async def test_delete_stays_delete(self):
        """'delete' остаётся action='delete' для ARQ и передаёт event_ids"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-delete-101"
        mock_arq.enqueue_job.return_value = mock_job
        
        event_ids = [401]
        
        job_id = await put_to_arq_bg_bulk(mock_arq, event_ids, "delete")
        
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][0] == "admin_request_bulk_action_users"
        assert call_args[0][1] == "delete"
        assert call_args[0][2] == event_ids
        assert job_id == "job-delete-101"


class TestPutToArqBgResetTraffic:
    """Тесты для reset_traffic - использует другую ARQ задачу"""
    
    @pytest.mark.asyncio
    async def test_reset_traffic_uses_correct_task(self):
        """'reset_traffic' вызывает reset_day_user_traffic с event_ids"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-reset-202"
        mock_arq.enqueue_job.return_value = mock_job
        
        event_ids = [501, 502]
        
        job_id = await put_to_arq_bg_bulk(mock_arq, event_ids, "reset_traffic")
        
        mock_arq.enqueue_job.assert_called_once()
        call_args = mock_arq.enqueue_job.call_args
        
        # Для reset_traffic вызывается другая задача
        assert call_args[0][0] == "reset_day_user_traffic"
        # Первый аргумент - массив event_ids (без action)
        assert call_args[0][1] == event_ids
        assert job_id == "job-reset-202"
    
    @pytest.mark.asyncio
    async def test_reset_traffic_with_empty_event_ids(self):
        """reset_traffic с пустым массивом event_ids"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-reset-empty"
        mock_arq.enqueue_job.return_value = mock_job
        
        event_ids = []
        
        job_id = await put_to_arq_bg_bulk(mock_arq, event_ids, "reset_traffic")
        
        call_args = mock_arq.enqueue_job.call_args
        assert call_args[0][0] == "reset_day_user_traffic"
        assert call_args[0][1] == []
        assert job_id == "job-reset-empty"


class TestPutToArqBgParameterOrder:
    """Тесты проверки порядка параметров в вызовах ARQ"""
    
    @pytest.mark.asyncio
    async def test_admin_request_bulk_action_users_parameter_order(self):
        """Параметры передаются в правильном порядке: task_name, action, event_ids"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-order-test"
        mock_arq.enqueue_job.return_value = mock_job
        
        event_ids = [601, 602]
        
        await put_to_arq_bg_bulk(mock_arq, event_ids, "activate")
        
        # Проверяем что позиционные аргументы переданы в правильном порядке
        call_args = mock_arq.enqueue_job.call_args[0]
        assert len(call_args) == 3
        assert call_args[0] == "admin_request_bulk_action_users"  # task_name
        assert call_args[1] == "add"  # action
        assert call_args[2] == event_ids  # event_ids list
    
    @pytest.mark.asyncio
    async def test_reset_day_user_traffic_parameter_order(self):
        """reset_day_user_traffic получает только event_ids (без action)"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-reset-order"
        mock_arq.enqueue_job.return_value = mock_job
        
        event_ids = [701, 702, 703]
        
        await put_to_arq_bg_bulk(mock_arq, event_ids, "reset_traffic")
        
        # Проверяем что передан только task_name и event_ids
        call_args = mock_arq.enqueue_job.call_args[0]
        assert len(call_args) == 2
        assert call_args[0] == "reset_day_user_traffic"  # task_name
        assert call_args[1] == event_ids  # event_ids list (без action!)
    
    @pytest.mark.asyncio
    async def test_event_ids_data_structure(self):
        """Проверяем что event_ids передаются как list[int]"""
        mock_arq = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-structure-test"
        mock_arq.enqueue_job.return_value = mock_job
        
        # Используем реалистичные event_ids
        event_ids = [801, 802, 803]
        
        await put_to_arq_bg_bulk(mock_arq, event_ids, "deactivate")
        
        # Проверяем что event_ids не изменились
        call_args = mock_arq.enqueue_job.call_args[0]
        passed_event_ids = call_args[2]
        
        assert passed_event_ids == event_ids
        assert len(passed_event_ids) == 3
        # Проверяем что все элементы int
        assert all(isinstance(eid, int) for eid in passed_event_ids)

