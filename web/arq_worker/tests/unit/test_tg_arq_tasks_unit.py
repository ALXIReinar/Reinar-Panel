"""
Unit тесты для TG-связанных ARQ задач.

Тестируем:
1. send_sub_link_tg_user - отправка ссылки на подписку через TG Bot API

Используем mock для aiohttp и fake контекст для ARQ.

ПРИМЕЧАНИЕ: Функция group_users_by_node_proto_id удалена в новой архитектуре,
так как SQL запросы теперь сразу возвращают данные сгруппированные по нодам.
"""
import pytest

from web.arq_worker.funcs.tg_sub_sender import send_sub_link_tg_user


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
        from web.arq_worker.tests.conftest import FakeAiohttpSession
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
