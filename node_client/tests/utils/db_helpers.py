"""
Утилиты для работы с тестовой БД
"""
import asyncpg
from typing import Optional


async def load_templates_by_protocol(pool: asyncpg.Pool, protocol_filters: str | list[str]) -> list[dict]:
    """
    Загружает ВСЕ шаблоны протокола из БД по фильтру(ам)
    
    Args:
        pool: Пул соединений с БД
        protocol_filters: Фильтр или список фильтров для поиска шаблонов.
                         Специальное значение "*" загружает ВСЕ шаблоны.
                         Примеры:
                         - "*" → все шаблоны (без фильтра)
                         - "xray" → все шаблоны содержащие "xray"
                         - "vless" → все шаблоны содержащие "vless"
                         - "xray-vless-reality-tcp" → точное совпадение
                         - ["xray", "shadowsocks"] → все шаблоны с "xray" или "shadowsocks"
    
    Returns:
        list[dict]: Список шаблонов (может быть пустым)
    """
    # Нормализуем к списку
    if isinstance(protocol_filters, str):
        filters = [f.strip() for f in protocol_filters.split(',')]
    else:
        filters = protocol_filters
    
    # Проверяем специальное значение "*" - загрузить ВСЕ шаблоны
    if len(filters) == 1 and filters[0] == "*":
        query = """
            SELECT 
                id, title, proto_python_lib,
                api_bulk_add_user_script, api_bulk_delete_user_script,
                reload_core_command, metrics_command, api_metrics_script, metrics_parser_code,
                bulk_add_script_custom_params, bulk_delete_script_custom_params,
                is_accepted, status
            FROM proto_templates
            WHERE is_accepted = true
            ORDER BY id
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(row) for row in rows]
    
    # Строим SQL с OR условиями для каждого фильтра
    # LIKE '%filter%' найдёт filter в любой части title
    where_conditions = " OR ".join([f"LOWER(title) LIKE ${i+1}" for i in range(len(filters))])
    like_params = [f"%{f.lower()}%" for f in filters]
    
    query = f"""
        SELECT 
            id, title, proto_python_lib,
            api_bulk_add_user_script, api_bulk_delete_user_script,
            reload_core_command, metrics_command, api_metrics_script, metrics_parser_code,
            bulk_add_script_custom_params, bulk_delete_script_custom_params,
            is_accepted, status
        FROM proto_templates
        WHERE ({where_conditions}) AND is_accepted = true
        ORDER BY id
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *like_params)
        return [dict(row) for row in rows]


async def load_template_by_protocol(pool: asyncpg.Pool, protocol_filters: str | list[str]) -> Optional[dict]:
    """
    Загружает ПЕРВЫЙ шаблон протокола из БД по фильтру(ам)
    
    Обёртка над load_templates_by_protocol() для обратной совместимости.
    
    Args:
        pool: Пул соединений с БД
        protocol_filters: Фильтр или список фильтров
    
    Returns:
        dict или None: Первый найденный шаблон или None
    """
    templates = await load_templates_by_protocol(pool, protocol_filters)
    return templates[0] if templates else None


async def load_template_by_id(pool: asyncpg.Pool, template_id: int) -> Optional[dict]:
    """
    Загружает шаблон протокола из БД по ID
    
    Args:
        pool: Пул соединений с БД
        template_id: ID шаблона
    
    Returns:
        dict или None: Словарь с полями шаблона или None если не найден
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 
                id, title, proto_python_lib,
                api_bulk_add_user_script, api_bulk_delete_user_script,
                reload_core_command, metrics_command, api_metrics_script, metrics_parser_code,
                bulk_add_script_custom_params, bulk_delete_script_custom_params,
                is_accepted, status
            FROM proto_templates
            WHERE id = $1
            LIMIT 1
            """,
            template_id
        )
        
        if row:
            return dict(row)
        return None


async def get_all_active_templates(pool: asyncpg.Pool) -> list[dict]:
    """
    Получает все активные шаблоны протоколов
    
    Args:
        pool: Пул соединений с БД
    
    Returns:
        list[dict]: Список активных шаблонов
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT 
                id, title, proto_python_lib, is_accepted, status
            FROM proto_templates
            WHERE is_accepted = true
            ORDER BY id
            """
        )
        
        return [dict(row) for row in rows]



async def load_templates_with_extractors(pool: asyncpg.Pool, protocol_filters: str | list[str]) -> list[dict]:
    """
    Загружает шаблоны протоколов вместе с их extractors из БД
    
    Расширенная версия load_templates_by_protocol, которая также загружает
    связанные extractors из таблицы templates_users_extractors.
    
    Args:
        pool: Пул соединений с БД
        protocol_filters: Фильтр или список фильтров для поиска шаблонов.
                         Специальное значение "*" загружает ВСЕ шаблоны.
    
    Returns:
        list[dict]: Список шаблонов с полем 'extractors' (список extractors)
    
    Example:
        >>> templates = await load_templates_with_extractors(pool, "xray")
        >>> for t in templates:
        ...     print(t['title'], len(t['extractors']))
        xray-vless-tcp 1
        xray-vmess-ws 2
    """
    # Нормализуем к списку
    if isinstance(protocol_filters, str):
        filters = [f.strip() for f in protocol_filters.split(',')]
    else:
        filters = protocol_filters
    
    # Проверяем специальное значение "*" - загрузить ВСЕ шаблоны
    if len(filters) == 1 and filters[0] == "*":
        query = """
            SELECT 
                pt.id, pt.title, pt.proto_python_lib,
                pt.api_bulk_add_user_script, pt.api_bulk_delete_user_script,
                pt.reload_core_command, pt.metrics_command, pt.api_metrics_script, pt.metrics_parser_code,
                pt.bulk_add_script_custom_params, pt.bulk_delete_script_custom_params,
                pt.constant_user_data_obj, pt.required_user_data_obj,
                pt.is_accepted, pt.status,
                (
                    SELECT json_agg(
                        json_build_object(
                            'id', tue.id,
                            'flatten_array_cursor', tue.flatten_array_cursor,
                            'extractor_script', tue.extractor_script,
                            'libs', tue.libs
                        )
                    )
                    FROM templates_users_extractors tue
                    WHERE tue.tmp_id = pt.id
                ) as extractors
            FROM proto_templates pt
            WHERE pt.is_accepted = true
            ORDER BY pt.id
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(row) for row in rows]
    
    # Строим SQL с OR условиями для каждого фильтра
    where_conditions = " OR ".join([f"LOWER(pt.title) LIKE ${i+1}" for i in range(len(filters))])
    like_params = [f"%{f.lower()}%" for f in filters]
    
    query = f"""
        SELECT 
            pt.id, pt.title, pt.proto_python_lib,
            pt.api_bulk_add_user_script, pt.api_bulk_delete_user_script,
            pt.reload_core_command, pt.metrics_command, pt.api_metrics_script, pt.metrics_parser_code,
            pt.bulk_add_script_custom_params, pt.bulk_delete_script_custom_params,
            pt.constant_user_data_obj, pt.required_user_data_obj,
            pt.is_accepted, pt.status,
            (
                SELECT json_agg(
                    json_build_object(
                        'id', tue.id,
                        'flatten_array_cursor', tue.flatten_array_cursor,
                        'extractor_script', tue.extractor_script,
                        'libs', tue.libs
                    )
                )
                FROM templates_users_extractors tue
                WHERE tue.tmp_id = pt.id
            ) as extractors
        FROM proto_templates pt
        WHERE ({where_conditions}) AND pt.is_accepted = true
        ORDER BY pt.id
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *like_params)
        return [dict(row) for row in rows]
