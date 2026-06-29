"""
Утилиты для работы с тестовой БД
"""
import asyncpg
from typing import Optional


async def load_template_by_protocol(pool: asyncpg.Pool, protocol_name: str) -> Optional[dict]:
    """
    Загружает шаблон протокола из БД по имени протокола
    
    Args:
        pool: Пул соединений с БД
        protocol_name: Название протокола (xray, hysteria2, shadowsocks)
    
    Returns:
        dict или None: Словарь с полями шаблона или None если не найден
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 
                id, title, proto_python_lib, api_add_user_script, api_delete_user_script,
                api_bulk_add_user_script, api_bulk_delete_user_script,
                flatten_json_users_key, flatten_user_identifier_key, 
                reload_core_command, metrics_command, api_metrics_script,
                add_script_custom_params, delete_script_custom_params,
                bulk_add_script_custom_params, bulk_delete_script_custom_params,
                is_accepted, status
            FROM proto_templates
            WHERE LOWER(title) LIKE $1 AND is_accepted = true
            LIMIT 1
            """,
            f"%{protocol_name.lower()}%"
        )
        
        if row:
            return dict(row)
        return None


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
                id, title, proto_python_lib, api_add_user_script, api_delete_user_script,
                api_bulk_add_user_script, api_bulk_delete_user_script,
                flatten_json_users_key, flatten_user_identifier_key, 
                reload_core_command, metrics_command, api_metrics_script,
                add_script_custom_params, delete_script_custom_params,
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
