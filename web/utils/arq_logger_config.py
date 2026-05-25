import os
import inspect
import logging
from logging.config import dictConfig
from typing import Literal, Any

from web.utils.logger_config import logger_settings_arq, lvls

dictConfig(logger_settings_arq) # Используем тот же конфиг, но с другим расположением файлов под логи
arq_logger = logging.getLogger('prod_log')


def log_event(event: Any, *args, level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO', **extra):
    event = str(event)
    cur_call = inspect.currentframe()
    outer = inspect.getouterframes(cur_call)[1]
    filename = os.path.relpath(outer.filename)
    func = outer.function
    line = outer.lineno

    message = event % args if args else event

    arq_logger.log(lvls[level], message, extra={
        'location': filename,
        'func': func,
        'line': line,
        **extra
    })
