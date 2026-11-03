"""
Unit тесты запроса служебных данных у админки: fetch_startup_data

Тестируем число попыток подключения:
- при старте — env.startup_retries попыток с паузой между ними (требование 3.6)
- при явном retries=1 (реинициализация) — одна попытка без пауз
"""

from unittest.mock import AsyncMock, patch

import pytest

from node_client.config import env
from node_client.startup import fetch_startup_data

# Порт 1 закрыт: соединение отклоняется сразу, без ожидания таймаута
UNREACHABLE_ADMIN = "http://127.0.0.1:1"


@pytest.mark.asyncio
async def test_fetch_startup_data_retries_by_settings():
    """Без явного retries делается env.startup_retries попыток, между ними пауза"""
    sleep = AsyncMock()
    with (
        patch.object(env, "admin_panel_url", UNREACHABLE_ADMIN),
        patch.object(env, "startup_retries", 3),
        patch("node_client.startup.asyncio.sleep", sleep),
        pytest.raises(RuntimeError, match="попыток: 3"),
    ):
        await fetch_startup_data([])

    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_fetch_startup_data_single_attempt():
    """retries=1 — одна попытка, без пауз, сразу ошибка"""
    sleep = AsyncMock()
    with (
        patch.object(env, "admin_panel_url", UNREACHABLE_ADMIN),
        patch.object(env, "startup_retries", 30),
        patch("node_client.startup.asyncio.sleep", sleep),
        pytest.raises(RuntimeError, match="попыток: 1"),
    ):
        await fetch_startup_data([1], retries=1)

    sleep.assert_not_awaited()
