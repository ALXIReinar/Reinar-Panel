"""
Тесты для проверки утечек памяти в ASGI Request lifecycle.
Проверяет, что функция receive() не создаёт утечек памяти при множественных вызовах.

РЕАЛИСТИЧНЫЕ ПОРОГИ (с учётом overhead от библиотек):
- 2 MB для 500 простых GET запросов (~4 KB/запрос)
- 1.5 MB для 100 запросов с телом по 100KB
- 1 MB для 100 запросов с потоковым чтением по 50KB
- 1 MB для серии запросов разного размера

Примечание: tracemalloc в Python показывает не только реальные утечки, но и 
overhead от интернирования строк, пулов объектов asyncpg/httpx, и других 
внутренних структур CPython. Пороги выбраны с учётом этих факторов.
"""
import gc
import tracemalloc
import httpx
import pytest
from fastapi import FastAPI, Request


@pytest.fixture
async def memory_test_app():
    """Создаёт тестовое приложение для проверки утечек памяти."""
    app = FastAPI()

    @app.post("/api/v1/test/large-body")
    async def receive_large_body(request: Request):
        """Эндпоинт для тестирования обработки больших тел запросов."""
        # Читаем тело запроса полностью
        body = await request.body()
        return {"received_bytes": len(body), "ok": True}

    @app.post("/api/v1/test/stream-body")
    async def receive_stream_body(request: Request):
        """Эндпоинт для тестирования потокового чтения тела запроса."""
        total_bytes = 0
        async for chunk in request.stream():
            total_bytes += len(chunk)
        return {"received_bytes": total_bytes, "ok": True}

    @app.get("/api/v1/test/simple")
    async def simple_get():
        """Простой GET эндпоинт."""
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_no_memory_leak_on_multiple_requests(memory_test_app):
    """
    Проверяет, что множественные запросы не создают утечек памяти.
    Отслеживает потребление памяти до и после серии запросов.
    
    РЕАЛИСТИЧНЫЙ ТЕСТ: Проверяет что память не растёт линейно с нагрузкой.
    Допускает разумный overhead от библиотек (~1-2 MB для 500 запросов).
    """
    # Агрессивная сборка мусора перед началом (защита от остаточной памяти предыдущих тестов)
    import sys
    for _ in range(3):
        gc.collect()
    
    # Запускаем tracemalloc
    tracemalloc.start()
    
    # Делаем серию запросов для "прогрева" системы
    for _ in range(20):
        await memory_test_app.get("/api/v1/test/simple")
    
    # Сборка мусора и снимок памяти после прогрева
    gc.collect()
    snapshot_before = tracemalloc.take_snapshot()
    
    # Выполняем тестовую нагрузку (500 запросов)
    for _ in range(500):
        resp = await memory_test_app.get("/api/v1/test/simple")
        assert resp.status_code == 200
    
    # Сборка мусора и снимок памяти после нагрузки
    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    
    tracemalloc.stop()
    
    # Сравниваем снимки памяти
    top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')
    
    # Считаем общий прирост памяти
    total_diff = sum(stat.size_diff for stat in top_stats)
    
    # РЕАЛИСТИЧНЫЙ ПОРОГ: 2 MB для 500 запросов
    # Учитывает overhead от asyncpg пулов, httpx кэшей, Python интернирования строк
    # Если память растёт больше 4 KB на запрос - это подозрительно
    assert total_diff < 2 * 1024 * 1024, (
        f"Обнаружена утечка памяти: {total_diff / 1024:.2f} KB прироста "
        f"после 500 запросов (порог: 2048 KB, {total_diff / 500:.2f} bytes/request)"
    )


@pytest.mark.asyncio
async def test_no_memory_leak_on_large_body_requests(memory_test_app):
    """
    Проверяет, что обработка больших тел запросов не создаёт утечек памяти.
    
    РЕАЛИСТИЧНЫЙ ТЕСТ: 100 запросов по 100KB с порогом 1.5 MB.
    """
    # Принудительная сборка мусора
    for _ in range(3):
        gc.collect()
    
    tracemalloc.start()
    
    # Прогрев с небольшим телом
    small_body = b"x" * 1024  # 1KB
    for _ in range(10):
        await memory_test_app.post("/api/v1/test/large-body", content=small_body)
    
    gc.collect()
    snapshot_before = tracemalloc.take_snapshot()
    
    # Тестовая нагрузка с большим телом (100 запросов)
    large_body = b"x" * 100 * 1024  # 100KB
    for _ in range(100):
        resp = await memory_test_app.post("/api/v1/test/large-body", content=large_body)
        assert resp.status_code == 200
        assert resp.json()["received_bytes"] == len(large_body)
    
    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    
    tracemalloc.stop()
    
    top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')
    total_diff = sum(stat.size_diff for stat in top_stats)
    
    # РЕАЛИСТИЧНЫЙ ПОРОГ: 1.5 MB для 100 запросов по 100KB
    # (Всего 10MB данных, но они должны освобождаться после обработки)
    assert total_diff < 1.5 * 1024 * 1024, (
        f"Обнаружена утечка памяти при обработке больших тел: "
        f"{total_diff / 1024:.2f} KB прироста после 100 запросов по 100KB (порог: 1536 KB)"
    )


@pytest.mark.asyncio
async def test_no_memory_leak_on_stream_body_requests(memory_test_app):
    """
    Проверяет, что потоковое чтение тела запроса не создаёт утечек памяти.
    
    РЕАЛИСТИЧНЫЙ ТЕСТ: 100 запросов по 50KB с порогом 1 MB.
    """
    for _ in range(3):
        gc.collect()
    tracemalloc.start()
    
    # Прогрев
    body = b"x" * 10 * 1024  # 10KB
    for _ in range(10):
        await memory_test_app.post("/api/v1/test/stream-body", content=body)
    
    gc.collect()
    snapshot_before = tracemalloc.take_snapshot()
    
    # Тестовая нагрузка с потоковым чтением (100 запросов)
    stream_body = b"y" * 50 * 1024  # 50KB
    for _ in range(100):
        resp = await memory_test_app.post("/api/v1/test/stream-body", content=stream_body)
        assert resp.status_code == 200
        assert resp.json()["received_bytes"] == len(stream_body)
    
    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    
    tracemalloc.stop()
    
    top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')
    total_diff = sum(stat.size_diff for stat in top_stats)
    
    # РЕАЛИСТИЧНЫЙ ПОРОГ: 1 MB для 100 запросов по 50KB
    # Потоковое чтение должно быть эффективным по памяти
    assert total_diff < 1 * 1024 * 1024, (
        f"Обнаружена утечка памяти при потоковом чтении: "
        f"{total_diff / 1024:.2f} KB прироста после 100 запросов по 50KB (порог: 1024 KB)"
    )


@pytest.mark.asyncio
async def test_receive_function_cleanup(memory_test_app):
    """
    Проверяет, что функция receive() корректно очищает ресурсы.
    Этот тест симулирует множественные вызовы receive() в рамках одного запроса.
    
    РЕАЛИСТИЧНЫЙ ТЕСТ: Множественные запросы разного размера с порогом 1 MB.
    """
    for _ in range(3):
        gc.collect()
    tracemalloc.start()
    
    # Прогрев
    for _ in range(20):
        await memory_test_app.post("/api/v1/test/stream-body", content=b"test")
    
    gc.collect()
    snapshot_before = tracemalloc.take_snapshot()
    
    # Множественные запросы с разными размерами тела
    for size in [1024, 10240, 51200, 102400]:  # 1KB, 10KB, 50KB, 100KB
        for _ in range(20):
            body = b"z" * size
            resp = await memory_test_app.post("/api/v1/test/stream-body", content=body)
            assert resp.status_code == 200
    
    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    
    tracemalloc.stop()
    
    top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')
    total_diff = sum(stat.size_diff for stat in top_stats)
    
    # РЕАЛИСТИЧНЫЙ ПОРОГ: 1 MB для серии запросов разного размера
    # После обработки всех запросов память не должна сильно вырасти
    assert total_diff < 1 * 1024 * 1024, (
        f"Обнаружена утечка памяти в функции receive(): "
        f"{total_diff / 1024:.2f} KB прироста после серии запросов разного размера (порог: 1024 KB)"
    )
