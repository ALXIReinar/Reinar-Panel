"""
Тесты для проверки работы логики деактивации подписок с infinite_traffic и infinite_expire флагами.
"""
import pytest
from web.sub.data.sql_queries.sub_sql import SubscriptionQueries
from web.sub.anything import PayStatuses


pytestmark = pytest.mark.asyncio


class TestInfiniteFlagsRevocation:
    """
    Проверяет что get_and_lock_expired_subs_grouped_by_node правильно обрабатывает
    infinite_traffic и infinite_expire флаги при деактивации подписок.
    """
    
    async def test_infinite_traffic_expired_date_deactivates(self, db_pool, db_seed, infinite_flags_test_seed):
        """
        Подписка с infinite_traffic=true, infinite_expire=false и истёкшим сроком
        ДОЛЖНА деактивироваться по дате.
        """
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                sq = SubscriptionQueries(conn)
                
                # Запускаем деактивацию
                result = await sq.get_and_lock_expired_subs_grouped_by_node()
                
                # Извлекаем все UUID из результата
                deactivated_uuids = []
                for node_group in result:
                    for user in node_group['users']:
                        deactivated_uuids.append(user['uuid'])
                
                # Проверяем что подписка с безлимитным трафиком, но истёкшим сроком деактивирована
                assert infinite_flags_test_seed['uuid_inf_traffic'] in deactivated_uuids, \
                    "Подписка с infinite_traffic=true НО истёкшим сроком должна деактивироваться"
                
                # Проверяем что статус изменён в БД
                is_active = await conn.fetchval(
                    "SELECT is_active FROM user_subs WHERE uuid = $1",
                    infinite_flags_test_seed['uuid_inf_traffic']
                )
                assert is_active is False, "is_active должен быть false после деактивации"
    
    async def test_infinite_expire_overlimit_deactivates(self, db_pool, db_seed, infinite_flags_test_seed):
        """
        Подписка с infinite_traffic=false, infinite_expire=true и превышенным лимитом
        ДОЛЖНА деактивироваться по трафику.
        """
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                sq = SubscriptionQueries(conn)
                
                # Запускаем деактивацию
                result = await sq.get_and_lock_expired_subs_grouped_by_node()
                
                # Извлекаем все UUID из результата
                deactivated_uuids = []
                for node_group in result:
                    for user in node_group['users']:
                        deactivated_uuids.append(user['uuid'])
                
                # Проверяем что бессрочная подписка с превышенным лимитом деактивирована
                assert infinite_flags_test_seed['uuid_inf_expire'] in deactivated_uuids, \
                    "Бессрочная подписка с превышенным лимитом трафика должна деактивироваться"
                
                # Проверяем что статус изменён в БД
                is_active = await conn.fetchval(
                    "SELECT is_active FROM user_subs WHERE uuid = $1",
                    infinite_flags_test_seed['uuid_inf_expire']
                )
                assert is_active is False, "is_active должен быть false после деактивации"
    
    async def test_fully_unlimited_not_deactivates(self, db_pool, db_seed, infinite_flags_test_seed):
        """
        Подписка с infinite_traffic=true, infinite_expire=true
        НЕ ДОЛЖНА деактивироваться даже с истёкшим сроком и превышенным лимитом.
        """
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                sq = SubscriptionQueries(conn)
                
                # Запускаем деактивацию
                result = await sq.get_and_lock_expired_subs_grouped_by_node()
                
                # Извлекаем все UUID из результата
                deactivated_uuids = []
                for node_group in result:
                    for user in node_group['users']:
                        deactivated_uuids.append(user['uuid'])
                
                # Проверяем что полностью безлимитная подписка НЕ деактивирована
                assert infinite_flags_test_seed['uuid_fully_unlimited'] not in deactivated_uuids, \
                    "Полностью безлимитная подписка (infinite_traffic=true, infinite_expire=true) НЕ должна деактивироваться"
                
                # Проверяем что статус остался активным в БД
                is_active = await conn.fetchval(
                    "SELECT is_active FROM user_subs WHERE uuid = $1",
                    infinite_flags_test_seed['uuid_fully_unlimited']
                )
                assert is_active is True, "is_active должен остаться true для полностью безлимитной подписки"
    
    async def test_limited_expired_deactivates(self, db_pool, db_seed, infinite_flags_test_seed):
        """
        Обычная подписка с лимитами (infinite_traffic=false, infinite_expire=false)
        и истёкшим сроком ДОЛЖНА деактивироваться.
        """
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                sq = SubscriptionQueries(conn)
                
                # Запускаем деактивацию
                result = await sq.get_and_lock_expired_subs_grouped_by_node()
                
                # Извлекаем все UUID из результата
                deactivated_uuids = []
                for node_group in result:
                    for user in node_group['users']:
                        deactivated_uuids.append(user['uuid'])
                
                # Проверяем что обычная подписка с истёкшим сроком деактивирована
                assert infinite_flags_test_seed['uuid_limited_expired'] in deactivated_uuids, \
                    "Обычная подписка с лимитами и истёкшим сроком должна деактивироваться"
                
                # Проверяем что статус изменён в БД
                is_active = await conn.fetchval(
                    "SELECT is_active FROM user_subs WHERE uuid = $1",
                    infinite_flags_test_seed['uuid_limited_expired']
                )
                assert is_active is False, "is_active должен быть false после деактивации"
    
    async def test_deactivation_summary(self, db_pool, db_seed, infinite_flags_test_seed):
        """
        Сводный тест: проверяет что из 4 тестовых подписок деактивируются правильные 3.
        """
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                sq = SubscriptionQueries(conn)
                
                # Запускаем деактивацию
                result = await sq.get_and_lock_expired_subs_grouped_by_node()
                
                # Извлекаем все UUID из результата
                deactivated_uuids = set()
                for node_group in result:
                    for user in node_group['users']:
                        deactivated_uuids.add(user['uuid'])
                
                # Ожидаемые UUID для деактивации
                expected_deactivated = {
                    infinite_flags_test_seed['uuid_inf_traffic'],     # Безлимитный трафик, истёк срок
                    infinite_flags_test_seed['uuid_inf_expire'],      # Бессрочная, превышен лимит
                    infinite_flags_test_seed['uuid_limited_expired'], # С лимитами, истёк срок
                }
                
                # UUID которые НЕ должны деактивироваться
                should_not_deactivate = {
                    infinite_flags_test_seed['uuid_fully_unlimited'], # Полностью безлимитная
                }
                
                # Проверяем что все ожидаемые UUID присутствуют
                assert expected_deactivated.issubset(deactivated_uuids), \
                    f"Отсутствуют ожидаемые UUID. Ожидалось: {expected_deactivated}, найдено: {deactivated_uuids}"
                
                # Проверяем что ни один из НЕ_должных не деактивирован
                assert not should_not_deactivate.intersection(deactivated_uuids), \
                    f"Деактивированы UUID которые не должны были: {should_not_deactivate.intersection(deactivated_uuids)}"
