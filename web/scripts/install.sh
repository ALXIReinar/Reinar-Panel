#!/bin/bash

set -e  # Выход при ошибке

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Константы
INSTALL_BASE="/opt/reinar_panel"
INSTALL_DIR="$INSTALL_BASE/web"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Reinar Panel - Установка${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Проверка прав root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Скрипт должен быть запущен с правами root${NC}"
   echo "Используйте: sudo bash install.sh"
   exit 1
fi

echo -e "${GREEN}✓${NC} Права root подтверждены"

# Проверка OpenSSL
echo -e "\n${YELLOW}Проверка OpenSSL...${NC}"
if ! command -v openssl &> /dev/null; then
    echo -e "${YELLOW}OpenSSL не найден, устанавливаем...${NC}"
    apt-get update && apt-get install -y openssl
fi
echo -e "${GREEN}✓${NC} OpenSSL найден: $(openssl version)"

# Определение директории скрипта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Скрипт находится в web/scripts/, поднимаемся на уровень выше в web/
WEB_DIR="$(dirname "$SCRIPT_DIR")"

# Проверка наличия необходимых файлов
echo -e "\n${YELLOW}Проверка исходных файлов...${NC}"
REQUIRED_FILES=("docker-compose.admin.yml" "Dockerfile" "requirements.txt" "main.py")
REQUIRED_DIRS=("api" "config_dir" "data" "schemas" "utils")

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$WEB_DIR/$file" ]; then
        echo -e "${RED}✗${NC} Файл не найден: $file"
        echo "Убедитесь, что структура проекта корректна"
        exit 1
    fi
done

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ ! -d "$WEB_DIR/$dir" ]; then
        echo -e "${RED}✗${NC} Директория не найдена: $dir"
        echo "Убедитесь, что структура проекта корректна"
        exit 1
    fi
done

echo -e "${GREEN}✓${NC} Все необходимые файлы найдены"

# Проверка Docker
echo -e "\n${YELLOW}Проверка Docker...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗${NC} Docker не найден"
    echo "Установите Docker и повторите установку"
    echo "Инструкция: https://docs.docker.com/engine/install/"
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker найден: $(docker --version)"

# Проверка Docker Compose
if ! command -v docker compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}✗${NC} Docker Compose не найден"
    echo "Установите Docker Compose и повторите установку"
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker Compose найден"

# Интерактивный выбор домена для Admin Panel
echo -e "\n${YELLOW}Настройка домена для Admin Panel${NC}"
echo -e "${BLUE}Caddy будет использовать этот домен для HTTPS${NC}\n"

echo -e "${YELLOW}Варианты настройки:${NC}"
echo -e "  ${GREEN}1. localhost${NC} - для локального доступа (самоподписанный сертификат)"
echo -e "     Доступ: https://localhost"
echo -e "     ${YELLOW}⚠ Недоступно из интернета${NC}\n"

echo -e "  ${GREEN}2. Реальный домен${NC} - для доступа из интернета (Let's Encrypt сертификат)"
echo -e "     Пример: admin.example.com"
echo -e "     ${YELLOW}⚠ Требуется настройка DNS A-записи на публичный IP этого сервера${NC}\n"

DEFAULT_ADMIN_DOMAIN="localhost"

# Если переменная ADMIN_DOMAIN задана (например, в CI), используем её
if [ -z "$ADMIN_DOMAIN" ]; then
    read -p "Введите домен для Admin Panel (по умолчанию $DEFAULT_ADMIN_DOMAIN): " USER_DOMAIN
    ADMIN_DOMAIN=${USER_DOMAIN:-$DEFAULT_ADMIN_DOMAIN}
    
    # Валидация домена
    if [[ "$ADMIN_DOMAIN" =~ ^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$ ]] || [ "$ADMIN_DOMAIN" = "localhost" ]; then
        if [ "$ADMIN_DOMAIN" = "localhost" ]; then
            echo -e "${GREEN}✓${NC} Будет использован localhost (самоподписанный сертификат)"
            echo -e "${YELLOW}  Доступ только локально: https://localhost${NC}"
        else
            echo -e "${GREEN}✓${NC} Будет использован домен: $ADMIN_DOMAIN"
            echo -e "${YELLOW}  Убедитесь что DNS A-запись указывает на IP этого сервера${NC}"
            echo -e "${YELLOW}  Caddy автоматически получит Let's Encrypt сертификат${NC}"
        fi
    else
        echo -e "${RED}✗${NC} Некорректный домен"
        echo -e "${YELLOW}Установка отменена${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} Используется домен из переменной окружения: $ADMIN_DOMAIN"
fi

# Интерактивный выбор порта для админ-панели
echo -e "\n${YELLOW}Настройка порта для Admin Panel${NC}"
DEFAULT_PORT=8000

# Если переменная ADMIN_PORT задана (например, в CI), используем её
if [ -z "$ADMIN_PORT" ]; then
    while true; do
        read -p "Введите порт для Admin Panel (по умолчанию $DEFAULT_PORT): " USER_PORT
        USER_PORT=${USER_PORT:-$DEFAULT_PORT}
        
        # Проверка что порт - число
        if ! [[ "$USER_PORT" =~ ^[0-9]+$ ]]; then
            echo -e "${RED}✗${NC} Ошибка: Порт должен быть числом"
            continue
        fi
        
        # Проверка диапазона портов
        if [ "$USER_PORT" -lt 1024 ] || [ "$USER_PORT" -gt 65535 ]; then
            echo -e "${RED}✗${NC} Ошибка: Порт должен быть в диапазоне 1024-65535"
            continue
        fi
        
        # Проверка занятости порта
        if lsof -Pi :$USER_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
            echo -e "${RED}✗${NC} Порт $USER_PORT уже занят"
            echo -e "${YELLOW}Процесс использующий порт:${NC}"
            lsof -Pi :$USER_PORT -sTCP:LISTEN
            read -p "Выбрать другой порт? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo -e "${YELLOW}Установка отменена${NC}"
                exit 1
            fi
            continue
        fi
        
        echo -e "${GREEN}✓${NC} Порт $USER_PORT доступен"
        break
    done
    
    ADMIN_PORT=$USER_PORT
else
    echo -e "${GREEN}✓${NC} Используется порт из переменной окружения: $ADMIN_PORT"
fi

# Установка и настройка WireGuard сервера
echo -e "\n${YELLOW}Установка WireGuard для приватной сети${NC}"
echo -e "${BLUE}WireGuard создаст приватную сеть между сервисами (admin, sub, bot)${NC}\n"

WG_SCRIPT="/opt/vpn-panel/wireguard_setup/install_wg_server.sh"

if [ ! -f "$WG_SCRIPT" ]; then
    echo -e "${RED}✗${NC} Скрипт $WG_SCRIPT не найден"
    echo -e "${YELLOW}⚠${NC}  Пропуск установки WireGuard"
else
    # Проверка, установлен ли уже WireGuard
    if systemctl is-active --quiet wg-quick@wg0 2>/dev/null; then
        echo -e "${GREEN}✓${NC} WireGuard уже установлен и запущен"
        echo -e "\n${BLUE}Информация о сервере:${NC}"
        if [ -f "/etc/wireguard/server_info.txt" ]; then
            cat /etc/wireguard/server_info.txt
            echo
        else
            echo -e "${YELLOW}⚠${NC}  Файл server_info.txt не найден"
        fi
    else
        echo -e "${YELLOW}Запуск установки WireGuard сервера...${NC}\n"
        
        if bash "$WG_SCRIPT"; then
            if systemctl is-active --quiet wg-quick@wg0 2>/dev/null; then
                echo -e "\n${GREEN}✓${NC} WireGuard сервер успешно установлен и запущен"
            else
                echo -e "${RED}✗${NC} WireGuard установлен, но не запущен"
                echo -e "${YELLOW}⚠${NC}  Продолжаем установку без приватной сети"
            fi
        else
            echo -e "${RED}✗${NC} Ошибка установки WireGuard"
            echo -e "${YELLOW}⚠${NC}  Продолжаем установку без приватной сети"
        fi
    fi
fi


# Создание директории установки
echo -e "\n${YELLOW}Создание директории ${INSTALL_DIR}...${NC}"
mkdir -p "$INSTALL_DIR"
echo -e "${GREEN}✓${NC} Директория создана"

# Копирование файлов
echo -e "\n${YELLOW}Копирование файлов приложения...${NC}"

# Копируем всю структуру web/ в /opt/reinar_panel/web/
cp -r "$WEB_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true

echo -e "${GREEN}✓${NC} Файлы скопированы"

# Установка правильных прав для Docker
echo -e "\n${YELLOW}Установка прав доступа...${NC}"
chmod -R 755 "$INSTALL_DIR"
chmod -R 644 "$INSTALL_DIR/secrets/dumps"/*.sql 2>/dev/null || true
chmod 755 "$INSTALL_DIR/secrets/dumps" 2>/dev/null || true

# Проверка SELinux
if command -v getenforce &> /dev/null && [ "$(getenforce)" != "Disabled" ]; then
    echo -e "${YELLOW}SELinux обнаружен, настраиваем контекст для Docker...${NC}"
    # Сначала восстанавливаем дефолтный контекст
    restorecon -Rv "$INSTALL_DIR/secrets/dumps" 2>/dev/null || true
    # Затем применяем Docker-специфичный контекст
    chcon -R -t container_file_t "$INSTALL_DIR/secrets/dumps" 2>/dev/null || \
    chcon -R -t svirt_sandbox_file_t "$INSTALL_DIR/secrets/dumps" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} SELinux контекст настроен"
fi

echo -e "${GREEN}✓${NC} Права установлены"

# Генерация паролей для PostgreSQL
echo -e "\n${YELLOW}Генерация паролей для PostgreSQL...${NC}"

# PG Admin Password
if [ -z "$PG_ADMIN_PASSWORD" ]; then
    PG_ADMIN_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-24)
    echo -e "${GREEN}✓${NC} PG Admin пароль сгенерирован"
else
    echo -e "${GREEN}✓${NC} PG Admin пароль из переменной окружения"
fi

# PG CRUD Password
if [ -z "$PG_CRUD_PASSWORD" ]; then
    PG_CRUD_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-24)
    echo -e "${GREEN}✓${NC} PG CRUD пароль сгенерирован"
else
    echo -e "${GREEN}✓${NC} PG CRUD пароль из переменной окружения"
fi

# Redis Password
if [ -z "$REDIS_PASSWORD" ]; then
    REDIS_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-24)
    echo -e "${GREEN}✓${NC} Redis пароль сгенерирован"
else
    echo -e "${GREEN}✓${NC} Redis пароль из переменной окружения"
fi

# Создание SQL скрипта для инициализации ролей
echo -e "\n${YELLOW}Создание SQL скрипта инициализации БД...${NC}"
ENTRYPOINT_DIR="$INSTALL_DIR/db/docker-entrypoint"
mkdir -p "$ENTRYPOINT_DIR"

cat > "$ENTRYPOINT_DIR/00_roles.sql" <<SQLEOF
-- Создание CRUD пользователя с сгенерированным паролем
CREATE ROLE reinar_crud_user WITH LOGIN PASSWORD '${PG_CRUD_PASSWORD}';

-- Доступ к БД
GRANT CONNECT ON DATABASE reinar_db TO reinar_crud_user;

-- Доступ к схеме
GRANT USAGE ON SCHEMA public TO reinar_crud_user;

-- CRUD на все текущие таблицы
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO reinar_crud_user;

-- Автоматические права для новых таблиц
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO reinar_crud_user;
SQLEOF

chmod 644 "$ENTRYPOINT_DIR/00_roles.sql"
echo -e "${GREEN}✓${NC} SQL скрипт создан: $ENTRYPOINT_DIR/00_roles.sql"

# Генерация JWT ключей для JWT
echo -e "\n${YELLOW}Генерация JWT ключей для JWT...${NC}"
KEYS_DIR="$INSTALL_DIR/secrets/keys"
mkdir -p "$KEYS_DIR"

if [ ! -f "$KEYS_DIR/private_key.pem" ] || [ ! -f "$KEYS_DIR/public_key.pem" ]; then
    # Генерация приватного ключа
    openssl genrsa -out "$KEYS_DIR/private_key.pem" 2048
    # Генерация публичного ключа из приватного
    openssl rsa -in "$KEYS_DIR/private_key.pem" -outform PEM -pubout -out "$KEYS_DIR/public_key.pem"
    
    # Установка прав
    chmod 644 "$KEYS_DIR/private_key.pem"
    chmod 644 "$KEYS_DIR/public_key.pem"
    
    echo -e "${GREEN}✓${NC} JWT ключи сгенерированы"
else
    echo -e "${GREEN}✓${NC} JWT ключи уже существуют, пропускаем генерацию"
fi

# Путь к .env файлам
ENV_FILE="$INSTALL_DIR/.env"
ENV_API_FILE="$INSTALL_DIR/.env.api.prod"
ENV_ARQ_FILE="$INSTALL_DIR/arq_worker/.env.arq.prod"

# Создание или обновление .env файла для docker-compose
echo -e "\n${YELLOW}Настройка конфигурации Docker Compose...${NC}"

cat > "$ENV_FILE" <<ENVEOF
# Docker Compose Configuration
# Для работы docker compose healthcheck. Убедитесь, что в .env.api.prod эти переменные идентичны
ADMIN_PORT=${ADMIN_PORT}
ADMIN_DOMAIN=${ADMIN_DOMAIN}

# Redis
REDIS_PASSWORD=${REDIS_PASSWORD}

# PostgreSQL
PG_DB=reinar_db
PG_ADMIN=postgres
PG_ADMIN_PASSWORD=${PG_ADMIN_PASSWORD}
REDIS_PORT=6379
PG_PORT=5432
ENVEOF

echo -e "${GREEN}✓${NC} Конфигурация Docker Compose создана: $ENV_FILE"

# Создание или обновление .env.api.prod для приложения
echo -e "\n${YELLOW}Настройка конфигурации приложения (Admin API)...${NC}"

if [ ! -f "$ENV_API_FILE" ]; then
    cat > "$ENV_API_FILE" <<APIENVEOF
PYTHONUNBUFFERED=1

# PostgreSQL
PG_ADMIN=postgres
PG_ADMIN_PASSWORD=${PG_ADMIN_PASSWORD}
PG_USER=reinar_crud_user
PG_PASSWORD=${PG_CRUD_PASSWORD}
PG_DB=reinar_db
PG_HOST=127.0.0.1
PG_PORT=5432
PG_MAX_CONNECTIONS=50

# Redis
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_MAX_CONNECTIONS=50
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# Subscription settings
NODE_METRICS_QUEUE_LIMIT=8

# ARQ Settings
ARQ_QUEUE_NAME=arq:cron_background_queue
ARQ_MAX_JOBS=10
ARQ_JOB_TIMEOUT=300

# Application Configuration
APP_MODE=prod
POST_PROCESSING_RESPONSES=1
UVICORN_WORKERS=1
UVICORN_PORT=${ADMIN_PORT}
DOMAIN=http://localhost:${ADMIN_PORT}
ALLOWED_IPS=127.0.0.1,10.0.0.1
TRUSTED_PROXIES=127.0.0.1,10.0.0.1
APIENVEOF
    echo -e "${GREEN}✓${NC} Конфигурация Admin API создана: $ENV_API_FILE"
else
    echo -e "${YELLOW}Обновление существующего .env.api.prod...${NC}"
    
    # Обновляем UVICORN_PORT
    if grep -q "^UVICORN_PORT=" "$ENV_API_FILE"; then
        sed -i "s/^UVICORN_PORT=.*/UVICORN_PORT=${ADMIN_PORT}/" "$ENV_API_FILE"
    else
        echo "UVICORN_PORT=${ADMIN_PORT}" >> "$ENV_API_FILE"
    fi
    
    # Добавляем ARQ настройки, если их нет
    if ! grep -q "^ARQ_QUEUE_NAME=" "$ENV_API_FILE"; then
        echo "" >> "$ENV_API_FILE"
        echo "# ARQ Settings" >> "$ENV_API_FILE"
        echo "ARQ_QUEUE_NAME=arq:cron_background_queue" >> "$ENV_API_FILE"
        echo "ARQ_MAX_JOBS=10" >> "$ENV_API_FILE"
        echo "ARQ_JOB_TIMEOUT=300" >> "$ENV_API_FILE"
    fi
    
    # Добавляем Subscription настройки, если их нет
    if ! grep -q "^NODE_METRICS_QUEUE_LIMIT=" "$ENV_API_FILE"; then
        echo "" >> "$ENV_API_FILE"
        echo "# Subscription settings" >> "$ENV_API_FILE"
        echo "NODE_METRICS_QUEUE_LIMIT=8" >> "$ENV_API_FILE"
    fi
    
    echo -e "${GREEN}✓${NC} Конфигурация Admin API обновлена"
fi

# Создание или обновление .env.arq.prod для ARQ worker
echo -e "\n${YELLOW}Настройка конфигурации ARQ Worker...${NC}"

# Создаём директорию arq_worker если её нет
mkdir -p "$INSTALL_DIR/arq_worker"

if [ ! -f "$ENV_ARQ_FILE" ]; then
    cat > "$ENV_ARQ_FILE" <<ARQENVEOF
PYTHONUNBUFFERED=1

# PostgreSQL (должны совпадать с .env.api.prod)
PG_USER=reinar_crud_user
PG_PASSWORD=${PG_CRUD_PASSWORD}
PG_DB=reinar_db
PG_HOST=127.0.0.1
PG_PORT=5432
PG_MAX_CONNECTIONS=50

# Redis (должны совпадать с .env.api.prod)
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_MAX_CONNECTIONS=50
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# Subscription settings
NODE_METRICS_QUEUE_LIMIT=8

# ARQ Settings (должны совпадать с .env.api.prod)
ARQ_QUEUE_NAME=arq:cron_background_queue
ARQ_MAX_JOBS=10
ARQ_JOB_TIMEOUT=300
ACTION_ON_CORE_PROTO_LIMIT=10

# Telegram Bot (опционально - настройте если используете TG бота)
# TG_BOT_TOKEN=your_bot_token_here

# Application Configuration
APP_MODE=prod
ARQENVEOF
    echo -e "${GREEN}✓${NC} Конфигурация ARQ Worker создана: $ENV_ARQ_FILE"
else
    echo -e "${YELLOW}Обновление существующего .env.arq.prod...${NC}"
    
    
    # Добавляем ACTION_ON_CORE_PROTO_LIMIT если его нет
    if ! grep -q "^ACTION_ON_CORE_PROTO_LIMIT=" "$ENV_ARQ_FILE"; then
        sed -i "/^ARQ_JOB_TIMEOUT=/a ACTION_ON_CORE_PROTO_LIMIT=10" "$ENV_ARQ_FILE"
    fi
    
    echo -e "${GREEN}✓${NC} Конфигурация ARQ Worker обновлена"
fi

# Экспорт переменной для docker compose
export ADMIN_PORT

# Подготовка директорий логов с правильными правами
echo -e "\n${YELLOW}Подготовка директорий логов...${NC}"
mkdir -p "$INSTALL_DIR/web_logs" "$INSTALL_DIR/arq_worker/arq_logs"
chmod -R 777 "$INSTALL_DIR/web_logs" "$INSTALL_DIR/arq_worker/arq_logs"
echo -e "${GREEN}✓${NC} Директории логов подготовлены"

# Остановка существующих контейнеров
echo -e "\n${YELLOW}Остановка существующих контейнеров...${NC}"
cd "$INSTALL_DIR"
docker compose -f docker-compose.admin.yml down 2>/dev/null || true
echo -e "${GREEN}✓${NC} Контейнеры остановлены"

# Сборка и запуск
echo -e "\n${YELLOW}Сборка и запуск контейнеров...${NC}"
docker compose -f docker-compose.admin.yml up -d --build

# Ожидание запуска
echo -e "\n${YELLOW}Ожидание запуска сервисов...${NC}"
sleep 5

# Проверка статуса
if docker compose -f docker-compose.admin.yml ps | grep -q "Up"; then
    echo -e "${GREEN}✓${NC} Контейнеры успешно запущены"
else
    echo -e "${RED}✗${NC} Ошибка запуска контейнеров"
    echo "Проверьте логи: cd $INSTALL_DIR && docker compose -f docker-compose.admin.yml logs"
    exit 1
fi

# 1. Принудительно отдаем папку проекта текущему юзеру (UID 1000)
sudo chown -R 1000:1000 /opt/reinar_panel/

# Для всех папок ставим стандартные 755 (читать и заходить могут все, писать - только владелец)
find /opt/reinar_panel/ -type d -exec sudo chmod 755 {} +

# Для всех файлов ставим стандартные 644 (читать могут все, писать - только владелец)
find /opt/reinar_panel/ -type f -exec sudo chmod 644 {} +

# 2. Выставляем права 777 (разрешить чтение/запись ВСЕМ, включая любого юзера внутри докера)
sudo chmod -R 777 /opt/reinar_panel/web/arq_worker/arq_logs
sudo chmod -R 777 /opt/reinar_panel/web/web_logs

# Финальное сообщение
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Установка завершена успешно!${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "Директория установки: ${GREEN}${INSTALL_DIR}${NC}"
echo -e "Admin Panel доступна по адресу: ${GREEN}https://${ADMIN_DOMAIN}${NC}"
if [ "$ADMIN_DOMAIN" = "localhost" ]; then
    echo -e "${YELLOW}⚠  Самоподписанный сертификат - браузер покажет предупреждение${NC}"
    echo -e "${YELLOW}   Это нормально для localhost. Продолжите через 'Advanced' → 'Proceed'${NC}"
fi
echo ""

echo -e "${YELLOW}Управление сервисами:${NC}"
echo -e "  Перейти в директорию: ${BLUE}cd $INSTALL_DIR${NC}"
echo -e "  Статус:      ${BLUE}docker compose -f docker-compose.admin.yml ps${NC}"
echo -e "  Остановка:   ${BLUE}docker compose -f docker-compose.admin.yml down${NC}"
echo -e "  Запуск:      ${BLUE}docker compose -f docker-compose.admin.yml up -d${NC}"
echo -e "  Перезапуск:  ${BLUE}docker compose -f docker-compose.admin.yml restart${NC}"
echo -e "  Логи:        ${BLUE}docker compose -f docker-compose.admin.yml logs -f${NC}\n"

echo -e "${YELLOW}Конфигурация:${NC}"
echo -e "  Docker Compose: ${BLUE}$ENV_FILE${NC}"
echo -e "  Admin API:      ${BLUE}$ENV_API_FILE${NC}"
echo -e "  ARQ Worker:     ${BLUE}$ENV_ARQ_FILE${NC}"
echo -e "  JWT ключи:      ${BLUE}$INSTALL_DIR/secrets/keys/${NC}"
echo -e "  Домен:          ${BLUE}${ADMIN_DOMAIN}${NC}\n"

#echo -e "${YELLOW}Следующие шаги:${NC}"
#echo -e "  1. Добавьте ноды через Admin Panel"
#echo -e "  2. Установите Node Client на серверах: ${BLUE}cd /path/to/node_client && sudo bash install.sh${NC}"
#echo -e "  3. Настройте подключение между Admin Panel и нодами\n"
