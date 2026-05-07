# VPN Node Client

REST API клиент для управления VPN нодой. Принимает команды от главной админки и выполняет их локально на сервере.

## Возможности

- ✅ Выполнение команд на ноде через REST API
- ✅ Чтение конфигурационных файлов
- ✅ Запись конфигурационных файлов
- ✅ Systemd service для автозапуска
- ✅ Прямой доступ к VPN ядру на хосте
- ⏳ Валидация команд (в разработке)
- ⏳ mTLS аутентификация (в разработке)

## Требования

- Linux сервер (Ubuntu 20.04+, Debian 11+, CentOS 8+)
- Python 3.10 или выше
- Права root для установки

## Установка

### Автоматическая установка (рекомендуется)

```bash
# Клонируйте репозиторий или скопируйте файлы на сервер
cd node_client

# Запустите установочный скрипт
sudo bash install.sh
```

Скрипт автоматически:
- Проверит наличие Python 3.10+
- Создаст виртуальное окружение в `/opt/vpn-node-client`
- Установит зависимости
- Создаст systemd service
- Запустит сервис

### Ручная установка

```bash
# Создание директории
sudo mkdir -p /opt/vpn-node-client
cd /opt/vpn-node-client

# Копирование файлов
sudo cp -r /path/to/node_client/* .

# Создание виртуального окружения
sudo python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
deactivate

# Создание конфига
sudo cp .env.example .env.node.prod
sudo nano .env.node.prod  # Отредактируйте при необходимости

# Создание systemd unit (см. install.sh для примера)
sudo nano /etc/systemd/system/vpn-node-client.service

# Запуск
sudo systemctl daemon-reload
sudo systemctl enable vpn-node-client
sudo systemctl start vpn-node-client
```

## Управление сервисом

```bash
# Статус
sudo systemctl status vpn-node-client

# Запуск
sudo systemctl start vpn-node-client

# Остановка
sudo systemctl stop vpn-node-client

# Перезапуск
sudo systemctl restart vpn-node-client

# Просмотр логов
sudo journalctl -u vpn-node-client -f

# Просмотр последних 100 строк логов
sudo journalctl -u vpn-node-client -n 100
```

## Деинсталляция

```bash
sudo bash /opt/vpn-node-client/uninstall.sh
```

## API Endpoints

### Health Check
```
GET /health

Response: {
  "status": "ok",
  "service": "node-client",
  "version": "0.1.0"
}
```

### Выполнить команду
```
POST /node/execute
Body: {
  "command": "xray version"
}

Response: {
  "success": true,
  "stdout": "Xray 1.8.0...",
  "stderr": "",
  "exit_code": 0,
  "command": "xray version"
}
```

### Прочитать конфиг
```
POST /node/config/read
Body: {
  "path": "/etc/xray/config.json"
}

Response: {
  "success": true,
  "content": "{ ... }",
  "path": "/etc/xray/config.json"
}
```

### Записать конфиг
```
POST /node/config/write
Body: {
  "path": "/etc/xray/config.json",
  "content": "{ ... }"
}

Response: {
  "success": true,
  "message": "Файл успешно записан",
  "path": "/etc/xray/config.json"
}
```

## Конфигурация

Файл конфигурации: `/opt/vpn-node-client/.env.node.prod`

```env
NODE_PORT=8001
COMMAND_TIMEOUT=30
```

После изменения конфигурации перезапустите сервис:
```bash
sudo systemctl restart vpn-node-client
```

## Безопасность

⚠️ **ВАЖНО:** Текущая версия - MVP без валидации команд и аутентификации.

**Рекомендации:**
- Используйте firewall для ограничения доступа к порту 8001
- Настройте доступ только с IP главной админки
- Планируется добавление mTLS аутентификации

Пример настройки firewall (ufw):
```bash
# Разрешить доступ только с IP админки
sudo ufw allow from 192.168.1.100 to any port 8001

# Или через iptables
sudo iptables -A INPUT -p tcp -s 192.168.1.100 --dport 8001 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 8001 -j DROP
```

## Swagger документация

После установки доступна по адресу: `http://localhost:8001/docs`

## Структура установки

```
/opt/vpn-node-client/
├── venv/                    # Виртуальное окружение Python
├── node_client/             # Код приложения
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   └── api/
│       ├── execute_api.py
│       └── config_api.py
├── .env.node.prod          # Конфигурация
├── requirements.txt
├── install.sh              # Скрипт установки
├── uninstall.sh            # Скрипт деинсталляции
└── node_logs/              # Логи приложения

/etc/systemd/system/
└── vpn-node-client.service  # Systemd unit
```

## Troubleshooting

### Сервис не запускается

```bash
# Проверьте статус
sudo systemctl status vpn-node-client

# Проверьте логи
sudo journalctl -u vpn-node-client -n 50

# Проверьте права на файлы
ls -la /opt/vpn-node-client
```

### Порт уже занят

```bash
# Проверьте какой процесс использует порт 8001
sudo lsof -i :8001

# Измените порт в конфиге
sudo nano /opt/vpn-node-client/.env.node.prod
# NODE_PORT=8002

# Перезапустите сервис
sudo systemctl restart vpn-node-client
```

### Команды не выполняются

Убедитесь что:
- Сервис запущен от root (для доступа к системным командам)
- VPN бинарники доступны в PATH
- Проверьте логи выполнения команд

## Разработка

Для локальной разработки:

```bash
# Клонируйте репозиторий
git clone <repo>
cd node_client

# Создайте venv
python3 -m venv venv
source venv/bin/activate

# Установите зависимости
pip install -r requirements.txt

# Запустите в режиме разработки
python -m node_client.main
```

API будет доступен на `http://localhost:8001`
