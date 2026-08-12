import base64
import secrets
from uuid import uuid4

from asyncpg import Connection, ForeignKeyViolationError

from web.sub.anything import PayStatuses
from web.sub.config_dir.config import env


class PaymentQueries:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def order_subscription(self, user_id: int, tg_id: int, sub_plan_id: int, offer_id: int):
        query_tg_id2user_id = 'SELECT id FROM users WHERE tg_id = $1 AND is_deleted = false'
        query = '''
        WITH pay_meta AS (
            SELECT infinite_expire, infinite_traffic, traffic_limit_mb, traffic_limit_day_mb, ttl_days, cost
            FROM sub_plan_offers
            WHERE sub_plan_id = $2 AND id = $3
        )
        INSERT INTO pay_orders (user_id, status, infinite_expire, infinite_traffic, traffic_limit_mb, traffic_limit_day_mb, ttl_days, cost) 
        SELECT $1, $4, infinite_expire, infinite_traffic, traffic_limit_mb, traffic_limit_day_mb, ttl_days, cost
        FROM pay_meta
        RETURNING id, cost, user_id
        '''
        try:
            if not user_id:
                user_id = await self.conn.fetchval(query_tg_id2user_id, tg_id)

            return await self.conn.fetchrow(query, user_id, sub_plan_id, offer_id, PayStatuses.pending)
        except ForeignKeyViolationError:
            return None


    async def activate_subscription(self, order_id: int, user_id: int, sub_plan_id: int, offer_id: int):
        """
        Продление подписки НЕ сохраняет старые условия
        При продлении будет следующее
        1. Суммирование ОБЩЕГО лимита трафика. Взял 150ГБ, затем ещё 50 = 200ГБ, но использованный трафик НЕ обнулится
        2. Суммирование длительности. Оставалось 10 дней до истечения, купил на месяц = 40 дней

        Ограничения(Общий лимит трафика, лимит трафика на день, безлимит трафика, бессрочная подписка)
         - станут такими, как в выбранном предложении при продлении
        """
        query = """
        WITH updated_order AS (
            -- 1. Обновляем статус заказа
            UPDATE pay_orders SET status = $7 WHERE id = $1
        ),
        inp AS (
            -- 2. Входные переменные
            SELECT 
                $1::bigint AS order_id, 
                $2::bigint AS user_id, 
                $3::text AS uuid, 
                $4::text AS b64_id, 
                $5::int AS sub_plan_id, 
                true AS is_active
        )
        INSERT INTO user_subs (
            order_id, user_id, uuid, b64_id, sub_plan_id, is_active, 
            expire_date, 
            infinite_expire, infinite_traffic, traffic_limit_day, used_mb_limit
        )
        SELECT 
            inp.order_id, inp.user_id, inp.uuid, inp.b64_id, inp.sub_plan_id, inp.is_active,
            -- При ВСТАВКЕ (первая покупка): если infinite_expire, то дата не важна (или ставим NULL / +ttl)
            NOW() + (spo.ttl_days * INTERVAL '1 day'),
            spo.infinite_expire, 
            spo.infinite_traffic, 
            spo.traffic_limit_day_mb, 
            spo.traffic_limit_mb
        FROM inp
        JOIN sub_plan_offers spo ON spo.sub_plan_id = inp.sub_plan_id AND spo.sub_plan_id = $5 AND spo.id = $6
        
        ON CONFLICT (user_id, sub_plan_id) 
        DO UPDATE SET 
            order_id = EXCLUDED.order_id,
            is_active = true, 
            is_limited = false,
            
            -- 1. СРОК ДЕЙСТВИЯ (Флаг бессрочности строго берётся из НОВОГО офера)
            infinite_expire = EXCLUDED.infinite_expire,
            
            expire_date = CASE 
                -- Если офер бессрочный, дата не имеет значения
                WHEN EXCLUDED.infinite_expire THEN NULL
                -- Если текущая подписка активна и не истекла -> прибавляем дни офера к expire_date
                WHEN user_subs.is_active = true AND user_subs.expire_date > NOW() 
                THEN user_subs.expire_date + (EXCLUDED.expire_date - NOW())
                -- Если сгорела -> отсчитываем заново от NOW()
                ELSE EXCLUDED.expire_date
            END,
        
            -- 2. ТРАФИК (Флаг безлимита строго берётся из НОВОГО офера)
            infinite_traffic = EXCLUDED.infinite_traffic,
        
            -- 3. ОБЩИЙ ЛИМИТ ТРАФИКА (used_mb_limit)
            used_mb_limit = CASE
                -- Если новый офер БЕЗЛИМИТНЫЙ -> зануляем лимит (он больше не нужен)
                WHEN EXCLUDED.infinite_traffic THEN NULL
                
                -- Если старая подписка была безлимитной, а новый офер ОГРАНИЧЕННЫЙ -> ставим лимит из офера
                WHEN user_subs.infinite_traffic THEN EXCLUDED.used_mb_limit
                
                -- Если и старая, и новая подписка с лимитом -> СУММИРУЕМ трафик
                ELSE COALESCE(user_subs.used_mb_limit, 0) + EXCLUDED.used_mb_limit
            END,
        
            -- 4. ДНЕВНОЙ ЛИМИТ ТРАФИКА (Строго из нового офера)
            traffic_limit_day = EXCLUDED.traffic_limit_day,
            
            -- Сбрасываем дневной счетчик при активации нового офера
            traffic_used_day_mb = 0
        
        RETURNING id, uuid;
        """
        uuid = str(uuid4())
        b64_id = base64.urlsafe_b64encode(secrets.token_bytes(env.sub_link_bytes)).decode('utf-8').rstrip('=')
        return await self.conn.fetchrow(
            query, order_id, user_id, uuid, b64_id, sub_plan_id, offer_id, PayStatuses.success
        )