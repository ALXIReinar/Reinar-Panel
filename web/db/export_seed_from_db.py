
import json
import asyncio
from pathlib import Path
from datetime import datetime
from asyncpg import create_pool

from web.config_dir.config import pool_settings, env


async def export_seed_data():
    """Экспортирует актуальные данные из test-postgresql"""
    # Создаём пул подключений
    admin_pool_settings = pool_settings.copy()
    admin_pool_settings['user'], admin_pool_settings['password'] = env.pg_admin, env.pg_admin_password

    pool = await create_pool(**admin_pool_settings)
    
    try:
        async with pool.acquire() as conn:
            # 1. templates_statuses
            templates_statuses = await conn.fetch(
                "SELECT * FROM templates_statuses ORDER BY id"
            )

            # 2. proto_templates
            proto_templates_rows = await conn.fetch(
                "SELECT * FROM proto_templates ORDER BY id"
            )
            

            # 4. protocols
            protocols_rows = await conn.fetch(
                "SELECT * FROM protocols ORDER BY tmp_id, id"
            )
            
            # 5. templates_users_extractors (новая таблица!)
            templates_users_extractors_rows = await conn.fetch(
                "SELECT * FROM templates_users_extractors ORDER BY tmp_id, id"
            )
            
            # 6. pay_statuses
            pay_statuses = await conn.fetch(
                "SELECT * FROM pay_statuses ORDER BY id"
            )
            
            # 7. online_statuses
            online_statuses = await conn.fetch(
                "SELECT * FROM online_statuses ORDER BY id"
            )
            
            # 8. sub_nodes_operations
            sub_nodes_operations = await conn.fetch(
                "SELECT * FROM sub_nodes_operations ORDER BY id"
            )

            # 9. whitelist_commands
            whitelist_commands = await conn.fetch(
                "SELECT * FROM whitelist_commands ORDER BY id"
            )
            whitelist_commands_list = []
            for wc in whitelist_commands:
                wc = dict(wc)
                del wc['id']
                whitelist_commands_list.append(wc)

            # Конвертируем в dict
            result = {
                "templates_statuses": [dict(row) for row in templates_statuses],
                "proto_templates": [],
                "pay_statuses": [dict(row) for row in pay_statuses],
                "online_statuses": [dict(row) for row in online_statuses],
                "sub_nodes_operations": [dict(row) for row in sub_nodes_operations],
                "whitelist_commands": whitelist_commands_list,
            }
            
            # Обрабатываем proto_templates с вложенными данными
            for template_row in proto_templates_rows:
                template_dict = dict(template_row)
                template_id = template_dict['id']
                
                # Удаляем id (будет auto-increment при вставке)
                del template_dict['id']
                

                # Находим protocols для этого шаблона
                protocols = [
                    {
                        "name": dict(proto)['name'],
                        "created_at": dict(proto)['created_at'].strftime("%Y-%m-%d %H:%M:%S.%f") if dict(proto)['created_at'] else None,
                        "tmp_id": "proto_templates_CURRENT"
                    }
                    for proto in protocols_rows
                    if dict(proto)['tmp_id'] == template_id
                ]
                
                # Находим extractors для этого шаблона (НОВАЯ ТАБЛИЦА!)
                extractors = [
                    {
                        "flatten_array_cursor": dict(ext)['flatten_array_cursor'],
                        "extractor_script": dict(ext)['extractor_script'],
                        "libs": dict(ext)['libs'],
                        "tmp_id": "proto_templates_CURRENT"
                    }
                    for ext in templates_users_extractors_rows
                    if dict(ext)['tmp_id'] == template_id
                ]
                
                template_dict['protocols'] = protocols
                template_dict['templates_users_extractors'] = extractors
                
                result['proto_templates'].append(template_dict)
            
            return result
    
    finally:
        await pool.close()


def datetime_converter(o):
    """Конвертер для datetime объектов в JSON"""
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Type {type(o)} not serializable")


async def main():
    print("🔄 Экспорт seed данных из test-postgresql...")

    try:
        seed_data = await export_seed_data()
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        print("   Проверьте настройки TEST_POOL_SETTINGS в скрипте")
        return
    
    # Сохраняем в seed_data.json
    output_path = Path(__file__).parent / "seed_data.json"
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(seed_data, f, indent=2, ensure_ascii=False, default=datetime_converter)
    
    print(f"\n✅ Данные экспортированы в {output_path}")
    print(f"   📋 templates_statuses: {len(seed_data['templates_statuses'])} записей")
    print(f"   🎯 proto_templates: {len(seed_data['proto_templates'])} записей")
    
    # Показываем сколько вложенных данных
    total_protocols = sum(len(t['protocols']) for t in seed_data['proto_templates'])
    total_extractors = sum(len(t['templates_users_extractors']) for t in seed_data['proto_templates'])

    print(f"      ├─ protocols: {total_protocols}")
    print(f"      └─ templates_users_extractors: {total_extractors}")
    
    print(f"   💰 pay_statuses: {len(seed_data['pay_statuses'])} записей")
    print(f"   🌐 online_statuses: {len(seed_data['online_statuses'])} записей")
    print(f"   🔧 sub_nodes_operations: {len(seed_data['sub_nodes_operations'])} записей")
    print(f"   ✅ whitelist_commands: {len(seed_data['whitelist_commands'])} записей")
    
    print(f"\n📝 Для применения запустите: python web/db/seed_data.py")


if __name__ == '__main__':
    asyncio.run(main())
