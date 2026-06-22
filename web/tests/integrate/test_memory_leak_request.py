"""
Тесты для проверки утечек памяти в ASGI Request lifecycle.
Проверяет, что функция receive() не создаёт утечек памяти при множественных вызовах.

СТРОГИЕ ПОРОГИ:
- 200 KB для 500 простых GET запросов
- 500 KB для 100 запросов с телом по 100KB
- 400 KB для 100 запросов с потоковым чтением по 50KB
- 300 KB для серии запросов разного размера
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
    
    СТРОГИЙ ТЕСТ: Увеличенная нагрузка (500 запросов) и жёсткий порог (200 KB).
    """
    # Принудительная сборка мусора перед началом
    gc.collect()
    
    # Запускаем tracemalloc
    tracemalloc.start()
    
    # Делаем серию запросов для "прогрева" системы
    for _ in range(20):
        await memory_test_app.get("/api/v1/test/simple")
    
    # Сборка мусора и снимок памяти после прогрева
    gc.collect()
    snapshot_before = tracemalloc.take_snapshot()
    
    # Выполняем тестовую нагрузку (увеличено до 500)
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
    
    # СТРОГИЙ ПОРОГ: 200 KB для 500 простых запросов
    # Если память растёт больше - это утечка
    assert total_diff < 200 * 1024, (
        f"Обнаружена утечка памяти: {total_diff / 1024:.2f} KB прироста "
        f"после 500 запросов (порог: 200 KB)"
    )


@pytest.mark.asyncio
async def test_no_memory_leak_on_large_body_requests(memory_test_app):
    """
    Проверяет, что обработка больших тел запросов не создаёт утечек памяти.
    
    СТРОГИЙ ТЕСТ: Увеличенная нагрузка (100 запросов по 100KB) и жёсткий порог (500 KB).
    """
    # Принудительная сборка мусора
    gc.collect()
    
    tracemalloc.start()
    
    # Прогрев с небольшим телом
    small_body = b"x" * 1024  # 1KB
    for _ in range(10):
        await memory_test_app.post("/api/v1/test/large-body", content=small_body)
    
    gc.collect()
    snapshot_before = tracemalloc.take_snapshot()
    
    # Тестовая нагрузка с большим телом (увеличено до 100 запросов)
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
    
    # СТРОГИЙ ПОРОГ: 500 KB для 100 запросов по 100KB
    # (Всего 10MB данных, но они должны освобождаться после обработки)
    assert total_diff < 500 * 1024, (
        f"Обнаружена утечка памяти при обработке больших тел: "
        f"{total_diff / 1024:.2f} KB прироста после 100 запросов по 100KB (порог: 500 KB)"
    )


@pytest.mark.asyncio
async def test_no_memory_leak_on_stream_body_requests(memory_test_app):
    """
    Проверяет, что потоковое чтение тела запроса не создаёт утечек памяти.
    
    СТРОГИЙ ТЕСТ: Увеличенная нагрузка (100 запросов по 50KB) и жёсткий порог (400 KB).
    """
    gc.collect()
    tracemalloc.start()
    
    # Прогрев
    body = b"x" * 10 * 1024  # 10KB
    for _ in range(10):
        await memory_test_app.post("/api/v1/test/stream-body", content=body)
    
    gc.collect()
    snapshot_before = tracemalloc.take_snapshot()
    
    # Тестовая нагрузка с потоковым чтением (увеличено до 100 запросов)
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
    
    # СТРОГИЙ ПОРОГ: 400 KB для 100 запросов по 50KB
    # Потоковое чтение должно быть эффективным по памяти
    assert total_diff < 400 * 1024, (
        f"Обнаружена утечка памяти при потоковом чтении: "
        f"{total_diff / 1024:.2f} KB прироста после 100 запросов по 50KB (порог: 400 KB)"
    )


@pytest.mark.asyncio
async def test_receive_function_cleanup(memory_test_app):
    """
    Проверяет, что функция receive() корректно очищает ресурсы.
    Этот тест симулирует множественные вызовы receive() в рамках одного запроса.
    
    СТРОГИЙ ТЕСТ: Множественные запросы разного размера и жёсткий порог (300 KB).
    """
    gc.collect()
    tracemalloc.start()
    
    # Прогрев
    for _ in range(20):
        await memory_test_app.post("/api/v1/test/stream-body", content=b"test")
    
    gc.collect()
    snapshot_before = tracemalloc.take_snapshot()
    
    # Множественные запросы с разными размерами тела (увеличено количество)
    for size in [1024, 10240, 51200, 102400]:  # 1KB, 10KB, 50KB, 100KB
        for _ in range(20):  # Увеличено с 10 до 20
            body = b"z" * size
            resp = await memory_test_app.post("/api/v1/test/stream-body", content=body)
            assert resp.status_code == 200
    
    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    
    tracemalloc.stop()
    
    top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')
    total_diff = sum(stat.size_diff for stat in top_stats)
    
    # СТРОГИЙ ПОРОГ: 300 KB для серии запросов разного размера
    # После обработки всех запросов память не должна сильно вырасти
    assert total_diff < 300 * 1024, (
        f"Обнаружена утечка памяти в функции receive(): "
        f"{total_diff / 1024:.2f} KB прироста после серии запросов разного размера (порог: 300 KB)"
    )
