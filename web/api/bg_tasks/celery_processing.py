import requests

from web.config_dir.celery_config import celery_bg
from web.config_dir.config import env
from web.utils.logger_config import log_event



"Периодические Задачи"
@celery_bg.task()
def run_rT_cleaner():
    log_event('Celery-Side, ставит крону очистки rT', level='WARNING')
    requests.delete(f'{env.app_url}/api/v1/server/crons/flush_refresh-tokens')


@celery_bg.task()
def traffic_sync():
    log_event('Celery-Side, Запуск кроны обновления трафика пользователей', level='WARNING')
    requests.get(f'{env.app_url}/api/v1/server/crons/traffic_sync')
