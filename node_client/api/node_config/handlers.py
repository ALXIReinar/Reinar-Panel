import shutil
import time
from pathlib import Path

from node_client.config import TMP_DIR
from node_client.utils.logger_config import log_event

BACKUP_DIR = Path(TMP_DIR) / "node_config_backups"
BACKUP_RETENTION_DAYS = 7
CLEANUP_INTERVAL_SECONDS = 3600  # Очистка раз в час

_last_cleanup_time = 0


async def create_backup(filepath: str) -> str:
    """
    Создаёт резервную копию файла конфигурации.

    Args:
        filepath: Путь к файлу конфигурации

    Returns:
        Путь к созданному бэкапу (или пустая строка, если файл не существует)
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    source_path = Path(filepath)
    if not source_path.exists():
        return ""

    # Формируем имя бэкапа: original_name_timestamp.backup
    timestamp = int(time.time())
    backup_name = f"{source_path.name}_{timestamp}.backup"
    backup_path = BACKUP_DIR / backup_name

    # Копируем файл с сохранением метаданных
    shutil.copy2(filepath, backup_path)

    # Очищаем старые бэкапы (throttled - раз в час)
    await cleanup_old_backups_throttled()

    return str(backup_path)


async def cleanup_old_backups_throttled():
    """Очистка с throttling - не чаще раза в час."""
    global _last_cleanup_time

    current_time = time.time()
    if current_time - _last_cleanup_time < CLEANUP_INTERVAL_SECONDS:
        return

    _last_cleanup_time = current_time
    await cleanup_old_backups()


async def cleanup_old_backups():
    """Удаляет бэкапы старше BACKUP_RETENTION_DAYS дней."""
    if not BACKUP_DIR.exists():
        return

    cutoff_time = time.time() - (BACKUP_RETENTION_DAYS * 86400)
    deleted_count = 0

    for backup_file in BACKUP_DIR.glob("*.backup"):
        try:
            if backup_file.stat().st_mtime < cutoff_time:
                backup_file.unlink()
                deleted_count += 1
        except Exception as e:
            log_event(f"Ошибка при удалении бэкапа {backup_file}: {e}", level='WARNING')

    if deleted_count > 0:
        log_event(f"Удалено старых бэкапов: {deleted_count}", level='INFO')