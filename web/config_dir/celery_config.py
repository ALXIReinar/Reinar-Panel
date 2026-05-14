from datetime import timedelta

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue
from kombu.serialization import register

from web.config_dir.config import redis_settings
from web.utils.celery_utils import json_loads, json_dumps


register(
    'serialize_asyncpg_json',
    json_dumps,
    json_loads,
    content_type='application/x-asyncpg-json',
    content_encoding='utf-8'
)

backend_result = broker = f"redis://{redis_settings['host']}:{redis_settings['port']}/0"

"Методы обмена"
ex_meth = 'ex_method'
exchange_mode = Exchange(ex_meth, type='direct')

"Очереди и их Роут-ключи"
# mail_queue = 'mail_queue'
# mail_routing_key = 'mail_routing_key'


celery_bg = Celery(
    'web',
    broker=broker,
    backend=backend_result,
    timezone='Europe/Moscow',
    result_expires=timedelta(minutes=10),

    task_serializer='serialize_asyncpg_json',
    result_serializer='serialize_asyncpg_json',
    accept_content=['serialize_asyncpg_json'],
    enable_utc=True,

    include=[
        'web.api.bg_tasks.metrics_collector',
    ],
    task_queues=[
    # Queue(mail_queue, exchange=exchange_mode, routing_key=mail_routing_key),
    ],
)

celery_bg.conf.beat_schedule = {
    'expired_rT_cleaner': {
        'task': 'web.api.bg_tasks.celery_processing.run_rT_cleaner',
        'schedule': crontab(day_of_month=[13, 28], hour=1, minute=2)
    },
    'traffic_synchronizer': {
        'task': 'web.api.bg_tasks.celery_processing.traffic_sync',
        'schedule': crontab(hour='*', minute='*/5',)
    },
}
