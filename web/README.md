# VPN Admin Panel - Установка

Админ-панель для централизованного управления VPN серверами через Docker.

## Требования

- **Docker** 20.10+
- **Docker Compose** 2.0+
- **Root доступ** для установки
- **Открытый порт** для админ-панели (по умолчанию 8000)

## Быстрая установка

```bash
cd web
sudo bash install.sh
```

Скрипт интерактивно запросит:
1. **Порт для админ-панели** (по умолчанию 8000)
2. **Приватный IP для WireGuard** (по умолчанию 10.0.0.1)

## Что делает скрипт установки

1. Проверяет наличие Docker и Docker Compose
2. Запрашивает порт для админ-панели (проверяет доступность)
3. Запрашивает приватный IP для WireGuard сети
4. Создаёт/обновляет `.env.api.prod` с настройками
5. Запускает контейнеры через `docker-compose`

## Структура после установки

```
web/
├── .env.api.prod          # Конфигурация (порт, IP, БД)
├── docker-compose.yml     # Описание сервисов
├── Dockerfile             # Образ приложения
├── install.sh             # Скрипт установки
├── uninstall.sh           # Скрипт деинсталляции
└── ...
```

## Управление сервисами

### Просмотр статуса
```bash
cd web
docker-compose ps
```

### Просмотр логов
```bash
docker-compose logs -f
docker-compose logs -f web-service  # Только админ-панель
docker-compose logs -f pg_db        # Только БД
```

### Перезапуск
```bash
docker-compose restart
docker-compose restart web-service  # Только админ-панель
```

### Остановка
```bash
docker-compose down
```

### Запуск после остановки
```bash
docker-compose up -d
```

## Деинсталляция

```bash
cd web
sudo bash uninstall.sh
```

**ВНИМАНИЕ**: Это удалит все контейнеры, volumes и данные БД!

## Конфигурация

Файл `.env.api.prod` содержит:

```env
# Порт админ-панели
ADMIN_PORT=8000

# Приватный IP для WireGuard
ADMIN_PRIVATE_IP=10.0.0.1

# PostgreSQL (автоматически)
PG_USER=vpn_admin
PG_PASSWORD=<сгенерированный>
PG_DB=vpn_admin_db
...
```

### Изменение порта после установки

1. Отредактируйте `.env.api.prod`:
   ```bash
   nano .env.api.prod
   # Измените ADMIN_PORT=8000 на нужный
   ```

2. Перезапустите:
   ```bash
   export ADMIN_PORT=<новый_порт>
   docker-compose up -d
   ```

## Доступ к админ-панели

После установки админ-панель доступна по адресу:
```
http://localhost:<ADMIN_PORT>
```

Swagger документация:
```
http://localhost:<ADMIN_PORT>/docs
```

## Следующие шаги

1. **Настройте WireGuard** для приватной сети между серверами
   ```bash
   cd ../wireguard_setup
   sudo bash install_wg_server.sh
   ```

2. **Установите Node Client** на VPN серверах
   ```bash
   cd ../node_client
   sudo bash install.sh
   ```

3. **Добавьте ноды** через Admin Panel API

## Troubleshooting

### Порт занят
```bash
# Проверить, что использует порт
sudo lsof -i :8000

# Остановить процесс или выбрать другой порт
```

### Контейнеры не запускаются
```bash
# Проверить логи
docker-compose logs

# Пересобрать образы
docker-compose up -d --build --force-recreate
```

### БД не подключается
```bash
# Проверить статус PostgreSQL
docker-compose logs pg_db

# Перезапустить БД
docker-compose restart pg_db
```

### Сбросить всё и начать заново
```bash
sudo bash uninstall.sh
sudo bash install.sh
```

## Архитектура

```
┌─────────────────────────────────────┐
│     VPN Admin Panel (Docker)        │
│  ┌──────────────┐  ┌──────────────┐ │
│  │ web-service  │  │  PostgreSQL  │ │
│  │   (FastAPI)  │──│   (pg_db)    │ │
│  └──────────────┘  └──────────────┘ │
│         │                            │
│    Port: 8000                        │
└─────────┼───────────────────────────┘
          │
          │ WireGuard (10.0.0.1)
          │
    ┌─────┴─────┐
    │           │
┌───▼───┐   ┌───▼───┐
│ Node  │   │ Node  │
│   #1  │   │   #2  │
└───────┘   └───────┘
```

## Безопасность

- Админ-панель слушает только `127.0.0.1` (localhost)
- Для удалённого доступа используйте **WireGuard** или **SSH туннель**
- БД доступна только внутри Docker сети
- Пароли генерируются автоматически

### SSH туннель (альтернатива WireGuard)
```bash
ssh -L 8000:localhost:8000 user@server
# Теперь доступно на http://localhost:8000
```
