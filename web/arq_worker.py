"""
ARQ Worker Process

Запуск:
    python -m arq web.config_dir.arq_config.WorkerSettings

Или через systemd:
    [Unit]
    Description=ARQ Worker for VPN Panel
    After=network.target redis.service postgresql.service

    [Service]
    Type=simple
    User=vpn-panel
    WorkingDirectory=/opt/vpn-panel/admin
    Environment="PYTHONPATH=/opt/vpn-panel/admin"
    ExecStart=/opt/vpn-panel/admin/.venv/bin/python -m arq web.config_dir.arq_config.WorkerSettings
    Restart=always
    RestartSec=10

    [Install]
    WantedBy=multi-user.target
"""

# Этот файл служит точкой входа для ARQ воркера
# Конфигурация находится в web.config_dir.arq_config.WorkerSettings

if __name__ == '__main__':
    import sys
    from arq import run_worker
    from web.config_dir.arq_config import WorkerSettings
    
    # Запуск воркера
    sys.exit(run_worker(WorkerSettings))
