"""
Замена zz_init_data.sql
- Самостоятельно накатит стартовые данные(шаблоны, статусы платежей, статусы пользователей, статусы нод и пр.)
- Будет предсказуемо отрабатывать при обновлениях
- и просто классный парень
"""
import json
import asyncio
from pathlib import Path
from typing import Any
from datetime import datetime
from asyncpg import create_pool, Connection

from web.config_dir.config import pool_settings


# Путь к JSON файлу с данными
SEED_DATA_PATH = Path(__file__).parent / "seed_data.json"


def load_seed_data() -> dict[str, Any]:
    """Загружает seed данные из JSON файла"""
    with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def convert_datetime_strings(data: Any) -> Any:
    """
    Рекурсивно конвертирует строки формата datetime в объекты datetime.
    Поддерживает форматы:
    - "2026-05-06 21:11:16.213501"
    - "2026-05-06 21:11:16"
    """
    if isinstance(data, dict):
        return {key: convert_datetime_strings(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_datetime_strings(item) for item in data]
    elif isinstance(data, str):
        # Пытаемся распарсить строку как datetime
        for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]:
            try:
                return datetime.strptime(data, fmt)
            except ValueError:
                continue
        return data
    else:
        return data


async def insert_with_fixed_id(
    conn: Connection,
    table: str,
    records: list[dict[str, Any]]
) -> None:
    """
    Вставка записей с фиксированным ID.
    Используется для таблиц, где ID жёстко привязан к коду (pay_statuses, online_statuses и т.д.)
    При конфликте ID обновляет все столбцы.
    """
    if not records:
        return
    
    inserted = 0
    updated = 0
    
    for record in records:
        # Формируем список колонок и значений
        columns = list(record.keys())
        placeholders = [f"${i+1}" for i in range(len(columns))]
        values = [record[col] for col in columns]
        
        # Формируем SET для UPDATE (все колонки кроме id)
        update_columns = [col for col in columns if col != 'id']
        update_set = ', '.join([f"{col} = EXCLUDED.{col}" for col in update_columns])
        
        query = f"""
            INSERT INTO {table} ({', '.join(columns)})
            OVERRIDING SYSTEM VALUE
            VALUES ({', '.join(placeholders)})
            ON CONFLICT (id) DO UPDATE SET {update_set}
            RETURNING (xmax = 0) AS inserted
        """
        
        # xmax = 0 означает INSERT, xmax > 0 означает UPDATE
        was_inserted = await conn.fetchval(query, *values)
        
        if was_inserted:
            inserted += 1
        else:
            updated += 1
    
    print(f"✓ {table}: вставлено {inserted}, обновлено {updated} из {len(records)} записей")


async def insert_adaptive(
    conn: Connection,
    table: str,
    records: list[dict[str, Any]],
    unique_fields: list[str]
) -> None:
    """
    Вставка записей без фиксированного ID (адаптивные).
    Проверяет существование по уникальным полям перед вставкой.
    """
    if not records:
        return
    
    inserted = 0
    for record in records:
        # Формируем условие для проверки существования
        where_conditions = []
        where_values = []
        for i, field in enumerate(unique_fields, 1):
            where_conditions.append(f"{field} = ${i}")
            where_values.append(record[field])
        
        # Проверяем существование
        check_query = f"SELECT 1 FROM {table} WHERE {' AND '.join(where_conditions)}"
        exists = await conn.fetchval(check_query, *where_values)
        
        if not exists:
            # Вставляем новую запись
            columns = list(record.keys())
            placeholders = [f"${i+1}" for i in range(len(columns))]
            values = [record[col] for col in columns]
            
            query = f"""
                INSERT INTO {table} ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
            """
            
            await conn.execute(query, *values)
            inserted += 1
    
    print(f"✓ {table}: вставлено {inserted} новых записей из {len(records)}")


async def insert_proto_templates(
    conn: Connection,
    templates: list[dict[str, Any]]
) -> None:
    """
    Вставка шаблонов протоколов с вложенными данными (template_spec_params, protocols, templates_users_extractors).
    Обрабатывает tmp_id для связи родитель-потомок.
    """
    if not templates:
        return
    
    inserted_templates = 0
    inserted_params = 0
    inserted_protocols = 0
    inserted_extractors = 0
    
    for template_data in templates:
        # Конвертируем datetime строки в объекты datetime
        template_data = convert_datetime_strings(template_data)
        # Извлекаем вложенные данные
        spec_params = template_data.pop("template_spec_params", [])
        protocols = template_data.pop("protocols", [])
        extractors = template_data.pop("templates_users_extractors", [])
        
        # Проверяем существование шаблона по title
        existing_id = await conn.fetchval(
            "SELECT id FROM proto_templates WHERE title = $1",
            template_data["title"]
        )
        
        if existing_id:
            template_id = existing_id
            print(f"  Шаблон '{template_data['title']}' уже существует (id={template_id})")
        else:
            # Вставляем шаблон и получаем его ID
            columns = list(template_data.keys())
            placeholders = [f"${i+1}" for i in range(len(columns))]
            values = [template_data[col] for col in columns]
            
            query = f"""
                INSERT INTO proto_templates ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                RETURNING id
            """
            
            template_id = await conn.fetchval(query, *values)
            inserted_templates += 1
            print(f"  Шаблон '{template_data['title']}' вставлен (id={template_id})")
        
        # Вставляем template_spec_params
        for param in spec_params:
            # Заменяем tmp_id на реальный template_id
            param_data = param.copy()
            param_data.pop("tmp_id", None)
            param_data["tmp_id"] = template_id
            
            # Проверяем существование параметра
            exists = await conn.fetchval(
                "SELECT 1 FROM template_spec_params WHERE key = $1 AND tmp_id = $2",
                param_data["key"], template_id
            )
            
            if not exists:
                await conn.execute(
                    "INSERT INTO template_spec_params (key, tmp_id) VALUES ($1, $2)",
                    param_data["key"], param_data["tmp_id"]
                )
                inserted_params += 1
        
        # Вставляем protocols
        for protocol in protocols:
            # Заменяем tmp_id на реальный template_id
            protocol_data = protocol.copy()
            protocol_data.pop("tmp_id", None)
            protocol_data["tmp_id"] = template_id
            
            # Проверяем существование протокола
            exists = await conn.fetchval(
                "SELECT 1 FROM protocols WHERE name = $1 AND tmp_id = $2",
                protocol_data["name"], template_id
            )
            
            if not exists:
                columns = list(protocol_data.keys())
                placeholders = [f"${i+1}" for i in range(len(columns))]
                values = [protocol_data[col] for col in columns]
                
                query = f"""
                    INSERT INTO protocols ({', '.join(columns)})
                    VALUES ({', '.join(placeholders)})
                """
                
                await conn.execute(query, *values)
                inserted_protocols += 1
        
        # Вставляем templates_users_extractors (НОВАЯ ТАБЛИЦА!)
        for extractor in extractors:
            # Заменяем tmp_id на реальный template_id
            extractor_data = extractor.copy()
            extractor_data.pop("tmp_id", None)
            extractor_data["tmp_id"] = template_id
            
            # Проверяем существование экстрактора по flatten_array_cursor + tmp_id
            exists = await conn.fetchval(
                "SELECT 1 FROM templates_users_extractors WHERE flatten_array_cursor = $1 AND tmp_id = $2",
                extractor_data["flatten_array_cursor"], template_id
            )
            
            if not exists:
                columns = list(extractor_data.keys())
                placeholders = [f"${i+1}" for i in range(len(columns))]
                values = [extractor_data[col] for col in columns]
                
                query = f"""
                    INSERT INTO templates_users_extractors ({', '.join(columns)})
                    VALUES ({', '.join(placeholders)})
                """
                
                await conn.execute(query, *values)
                inserted_extractors += 1
    
    print(f"✓ proto_templates: {inserted_templates} шаблонов, {inserted_params} параметров, {inserted_protocols} протоколов, {inserted_extractors} экстракторов")


async def seed_all(conn: Connection, seed_data: dict[str, Any]) -> None:
    """Вставка всех seed данных в правильном порядке"""
    
    print("\n=== Начало инициализации данных ===\n")
    
    # 1. Простые таблицы без FK
    print("1. Статусы шаблонов...")
    await insert_with_fixed_id(
        conn, "templates_statuses",
        seed_data.get("templates_statuses", []),
    )
    
    print("\n2. Статусы платежей...")
    await insert_with_fixed_id(
        conn, "pay_statuses",
        seed_data.get("pay_statuses", [])
    )
    
    print("\n3. Статусы онлайн...")
    await insert_with_fixed_id(
        conn, "online_statuses",
        seed_data.get("online_statuses", [])
    )
    
    print("\n4. Операции с нодами подписок...")
    await insert_with_fixed_id(
        conn, "sub_nodes_operations",
        seed_data.get("sub_nodes_operations", [])
    )
    
    print("\n5. Белый список команд...")
    await insert_adaptive(
        conn, "whitelist_commands",
        seed_data.get("whitelist_commands", []),
        ["command"]
    )
    
    # 2. Сложные таблицы с FK и вложенными данными
    print("\n6. Шаблоны протоколов (с вложенными данными)...")
    await insert_proto_templates(
        conn, seed_data.get("proto_templates", [])
    )
    
    print("\n=== Инициализация данных завершена ===\n")


async def init_data():
    """Главная функция инициализации данных"""
    # Загружаем seed данные
    seed_data = load_seed_data()
    print(f"Загружены seed данные из {SEED_DATA_PATH}")
    
    # Создаём пул подключений
    pool = await create_pool(**pool_settings)
    
    try:
        async with pool.acquire() as conn:
            # Выполняем все вставки в одной транзакции
            async with conn.transaction():
                await seed_all(conn, seed_data)
        
        print("✅ Все данные успешно инициализированы!")
    
    except Exception as e:
        print(f"❌ Ошибка при инициализации данных: {e}")
        raise
    
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(init_data())
