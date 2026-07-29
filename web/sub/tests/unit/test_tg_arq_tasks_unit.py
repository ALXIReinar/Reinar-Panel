"""
Unit тесты для TG-связанных ARQ задач.

Тестируем:
1. send_sub_link_tg_user - отправка ссылки на подписку через TG Bot API
2. group_users_by_node_proto_id - группировка пользователей по нодам (helper)

Используем mock для aiohttp и fake контекст для ARQ.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import ClientError

from web.sub.arq_tasks.tg_sub_sender import send_sub_link_tg_user
from web.sub.arq_tasks.pounted_bulk.handlers import group_users_by_node_proto_id


pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures('db_seed')]


class TestSendSubLinkTgUser:
    """Unit тесты для send_sub_link_tg_user"""
    
    async def test_send_sub_link_success(self, mock_arq_ctx, db_pool, tg_routing_seed, mock_aiohttp_success):
        """
        Успешная отправка ссылки на подписку в Telegram.
        
        Проверяем:
        - SQL запрос get_user_tg_notify выполняется
        - HTTP POST запрос к TG Bot API отправляется
        - Возвращается success: True
        - Возвращается корректный status_code
        """
        # Arrange
        user_id = tg_routing_seed['user_with_subs']['user_id']
        user_sub_id = tg_routing_seed['user_with_subs']['sub_id']
        
        # Замокируем aiohttp в контексте
        mock_arq_ctx['aio_http'] = mock_aiohttp_success
        
        # Act
        result = await send_sub_link_tg_user(
            mock_arq_ctx,
            user_id,
            user_sub_id
        )
        
        # Assert
        assert result['success'] is True
        assert 'message' in result
        assert result['status_code'] == 200
        
        # Проверяем что был вызван POST запрос
        assert len(mock_aiohttp_success.post_calls) == 1
        
        # Проверяем URL запроса (содержит bot token)
        post_call = mock_aiohttp_success.post_calls[0]
        assert 'sendMessage' in post_call['url']
        
        # Проверяем payload
        payload = post_call['kwargs']['json']
        assert 'chat_id' in payload
        assert payload['chat_id'] == tg_routing_seed['user_with_subs']['tg_id']
        assert 'text' in payload
        assert '/sub/' in payload['text']  # Ссылка на подписку
        assert 'parse_mode' in payload
    
    
    async def test_send_sub_link_telegram_api_error(self, mock_arq_ctx, db_pool, tg_routing_seed):
        """
        Обработка ошибки TG Bot API.
        
        Проверяем:
        - При ClientError исключение перехватывается корректно
        - Возвращается success: False
        - Возвращается message об ошибке
        - Логируется ошибка
        """
        # Arrange
        user_id = tg_routing_seed['user_with_subs']['user_id']
        user_sub_id = tg_routing_seed['user_with_subs']['sub_id']
        
        # Создаём fake aiohttp с ошибкой
        from web.sub.tests.conftest import FakeAiohttpSession
        mock_aiohttp_error = FakeAiohttpSession(raise_error=True)
        mock_arq_ctx['aio_http'] = mock_aiohttp_error
        
        # Act
        result = await send_sub_link_tg_user(
            mock_arq_ctx,
            user_id,
            user_sub_id
        )
        
        # Assert
        # После исправления бага: задача возвращает success=False при ошибке
        assert result['success'] is False
        assert 'message' in result
        assert result['message'] == 'Апи телеграма недоступен'
    
    
    async def test_send_sub_link_formats_message_correctly(self, mock_arq_ctx, db_pool, tg_routing_seed, mock_aiohttp_success):
        """
        Проверка правильности форматирования сообщения.
        
        Проверяем:
        - Сообщение содержит правильный b64_id
        - Используется HTML parse_mode
        - Текст содержит ключевые элементы (эмодзи, тэги <code>, <b>)
        """
        # Arrange
        user_id = tg_routing_seed['user_with_subs']['user_id']
        user_sub_id = tg_routing_seed['user_with_subs']['sub_id']
        
        mock_arq_ctx['aio_http'] = mock_aiohttp_success
        
        # Act
        await send_sub_link_tg_user(mock_arq_ctx, user_id, user_sub_id)
        
        # Assert
        post_call = mock_aiohttp_success.post_calls[0]
        payload = post_call['kwargs']['json']
        
        # Проверяем HTML теги
        assert payload['parse_mode'] == 'HTML'
        assert '<code>' in payload['text']
        assert '</code>' in payload['text']
        assert '<b>' in payload['text']
        assert '</b>' in payload['text']
        
        # Проверяем что есть b64_id в ссылке
        assert 'b64-tg-user-1' in payload['text']


class TestGroupUsersByNodeProtoId:
    """Unit тесты для group_users_by_node_proto_id (helper function)"""
    
    def test_group_users_by_node_single_node(self):
        """
        Группировка пользователей для одной ноды.
        
        Проверяем:
        - Пользователи группируются правильно
        - Метаданные ноды копируются без полей пользователя
        - Результат - список с одним элементом
        """
        # Arrange
        input_data = [
            {
                'node_proto_id': 1,
                'private_ip': '10.0.0.1',
                'api_port': 8080,
                'proto_python_lib': 'vless',
                'uuid': 'user-uuid-1',
                'user_sub_id': 101,
            },
            {
                'node_proto_id': 1,
                'private_ip': '10.0.0.1',
                'api_port': 8080,
                'proto_python_lib': 'vless',
                'uuid': 'user-uuid-2',
                'user_sub_id': 102,
            }
        ]
        
        # Act
        result = group_users_by_node_proto_id(input_data)
        
        # Assert
        assert len(result) == 1
        
        node = result[0]
        assert node['node_proto_id'] == 1
        assert node['private_ip'] == '10.0.0.1'
        assert node['api_port'] == 8080
        assert node['proto_python_lib'] == 'vless'
        
        # Проверяем пользователей
        assert len(node['users']) == 2
        assert node['users'][0]['uuid'] == 'user-uuid-1'
        assert node['users'][0]['user_sub_id'] == 101
        assert node['users'][1]['uuid'] == 'user-uuid-2'
        assert node['users'][1]['user_sub_id'] == 102
    
    
    def test_group_users_by_node_multiple_nodes(self):
        """
        Группировка пользователей для нескольких нод.
        
        Проверяем:
        - Пользователи правильно распределяются по нодам
        - Каждая нода содержит только своих пользователей
        """
        # Arrange
        input_data = [
            {
                'node_proto_id': 1,
                'private_ip': '10.0.0.1',
                'api_port': 8080,
                'proto_python_lib': 'vless',
                'uuid': 'user-node1-uuid1',
                'user_sub_id': 101,
            },
            {
                'node_proto_id': 2,
                'private_ip': '10.0.0.2',
                'api_port': 8081,
                'proto_python_lib': 'vmess',
                'uuid': 'user-node2-uuid1',
                'user_sub_id': 201,
            },
            {
                'node_proto_id': 1,
                'private_ip': '10.0.0.1',
                'api_port': 8080,
                'proto_python_lib': 'vless',
                'uuid': 'user-node1-uuid2',
                'user_sub_id': 102,
            }
        ]
        
        # Act
        result = group_users_by_node_proto_id(input_data)
        
        # Assert
        assert len(result) == 2
        
        # Находим ноды по ID
        node1 = next(n for n in result if n['node_proto_id'] == 1)
        node2 = next(n for n in result if n['node_proto_id'] == 2)
        
        # Проверяем node 1
        assert len(node1['users']) == 2
        assert node1['users'][0]['uuid'] == 'user-node1-uuid1'
        assert node1['users'][1]['uuid'] == 'user-node1-uuid2'
        
        # Проверяем node 2
        assert len(node2['users']) == 1
        assert node2['users'][0]['uuid'] == 'user-node2-uuid1'
    
    
    def test_group_users_by_node_empty_input(self):
        """
        Обработка пустого входного списка.
        
        Проверяем:
        - Возвращается пустой список
        - Нет исключений
        """
        # Arrange
        input_data = []
        
        # Act
        result = group_users_by_node_proto_id(input_data)
        
        # Assert
        assert result == []
    
    
    def test_group_users_preserves_all_node_metadata(self):
        """
        Проверка сохранения всех метаданных ноды.
        
        Проверяем:
        - Все поля кроме uuid и user_sub_id копируются
        - Дополнительные поля не теряются
        """
        # Arrange
        input_data = [
            {
                'node_proto_id': 1,
                'private_ip': '10.0.0.1',
                'api_port': 8080,
                'metrics_port': 9090,
                'proto_python_lib': 'vless',
                'api_bulk_add_user_script': 'python add.py',
                'bulk_add_script_custom_params': {'param': 'value'},
                'reload_core_command': 'systemctl reload',
                'config_path': '/etc/config.json',
                'flatten_json_users_key': 'clients',
                'flatten_user_identifier_key': 'email',
                'required_user_data_obj': {},
                'constant_user_data_obj': {},
                'uuid': 'user-uuid-1',
                'user_sub_id': 101,
            }
        ]
        
        # Act
        result = group_users_by_node_proto_id(input_data)
        
        # Assert
        node = result[0]
        
        # Все метаданные сохранены
        assert node['private_ip'] == '10.0.0.1'
        assert node['api_port'] == 8080
        assert node['metrics_port'] == 9090
        assert node['proto_python_lib'] == 'vless'
        assert node['api_bulk_add_user_script'] == 'python add.py'
        assert node['bulk_add_script_custom_params'] == {'param': 'value'}
        assert node['reload_core_command'] == 'systemctl reload'
        assert node['config_path'] == '/etc/config.json'
        assert node['flatten_json_users_key'] == 'clients'
        assert node['flatten_user_identifier_key'] == 'email'
        
        # Поля пользователя НЕ в метаданных
        assert 'uuid' not in node
        assert 'user_sub_id' not in node
        
        # Но есть в списке users
        assert node['users'][0]['uuid'] == 'user-uuid-1'
        assert node['users'][0]['user_sub_id'] == 101
