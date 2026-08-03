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
SUB_DIR="$INSTALL_DIR/sub"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  VPN Sub Service - Установка${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Проверка прав root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Скрипт должен быть запущен с правами root${NC}"
   echo "Используйте: sudo bash install.sh"
   exit 1
fi

echo -e "${GREEN}✓${NC} Права root подтверждены"

# Определение режима развертывания
echo -e "\n${YELLOW}Определение режима развертывания...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    DEPLOYMENT_MODE="shared"
    echo -e "${GREEN}✓${NC} Обнаружена Admin Panel на том же сервере (shared mode)"
    echo -e "${BLUE}  Sub Service будет использовать локальные БД и Redis через WireGuard${NC}"
else
    DEPLOYMENT_MODE="standalone"
    echo -e "${GREEN}✓${NC} Standalone развертывание (отдельный сервер)"
    echo -e "${BLUE}  Требуется подключение к приватной сети для доступа к БД и Redis${NC}"
fi

# Проверка Docker Compose
echo -e "\n${YELLOW}Проверка Docker Compose...${NC}"
if ! command -v docker compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}✗${NC} Docker Compose не найден"
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker Compose найден"

# Интерактивный выбор порта для sub сервиса
echo -e "\n${YELLOW}Настройка порта для Sub Service${NC}"
DEFAULT_PORT=8080

# Если переменная SUB_PORT задана (например, в CI), используем её
if [ -z "$SUB_PORT" ]; then
    while true; do
        read -p "Введите порт для Sub Service (по умолчанию $DEFAULT_PORT): " USER_PORT
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
    
    SUB_PORT=$USER_PORT
else
    echo -e "${GREEN}✓${NC} Используется порт из переменной окружения: $SUB_PORT"
fi

# Запрос Robokassa credentials
echo -e "\n${YELLOW}Настройка Robokassa${NC}"

# Если переменные заданы (например, в CI), используем их
if [ -z "$ROBO_SHOP_LOGIN" ]; then
    echo -e "${BLUE}Хотите настроить платёжную систему Robokassa?${NC}"
    echo -e "  ${GREEN}y${NC} - Настроить сейчас"
    echo -e "  ${YELLOW}n${NC} - Пропустить (можно настроить позже в .env.sub.prod)\n"
    
    read -p "Настроить Robokassa? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "Введите Robokassa Shop Login: " ROBO_SHOP_LOGIN
        read -p "Введите Robokassa Password 1: " ROBO_PASSW_1
        read -p "Введите Robokassa Password 2: " ROBO_PASSW_2
        echo -e "${GREEN}✓${NC} Robokassa настроена"
    else
        # Заглушки
        ROBO_SHOP_LOGIN="your_shop_login_here"
        ROBO_PASSW_1="your_password_1_here"
        ROBO_PASSW_2="your_password_2_here"
        echo -e "${YELLOW}⚠${NC}  Robokassa не настроена. Отредактируйте $SUB_DIR/.env.sub.prod позже"
    fi
else
    echo -e "${GREEN}✓${NC} Используются данные Robokassa из переменных окружения"
fi


# Настройка приватной сети и определение хостов БД/Redis
echo -e "\n${YELLOW}Настройка доступа к БД и Redis${NC}"

if [ "$DEPLOYMENT_MODE" = "shared" ]; then
    # Shared mode: используем 10.0.0.1 (локальный WireGuard)
    echo -e "${BLUE}Shared mode: используются локальные сервисы через WireGuard${NC}"
    PG_HOST="10.0.0.1"
    PG_PORT=5432
    REDIS_HOST="10.0.0.1"
    REDIS_PORT=6379
    echo -e "${GREEN}✓${NC} PostgreSQL: ${PG_HOST}:${PG_PORT}"
    echo -e "${GREEN}✓${NC} Redis: ${REDIS_HOST}:${REDIS_PORT}"
    
elif [ "$DEPLOYMENT_MODE" = "standalone" ]; then
    # Standalone mode: ПРИНУДИТЕЛЬНАЯ настройка WireGuard
    echo -e "${YELLOW}Standalone режим требует настройки приватной сети${NC}"
    echo -e "${BLUE}Sub Service должен подключиться к Admin Panel через WireGuard для доступа к БД${NC}\n"
    
    # Проверка WireGuard
    if ! command -v wg &> /dev/null; then
        echo -e "${YELLOW}WireGuard не установлен. Установка...${NC}"
        apt update && apt install -y wireguard wireguard-tools
        echo -e "${GREEN}✓${NC} WireGuard установлен"
    else
        echo -e "${GREEN}✓${NC} WireGuard уже установлен"
    fi
    
    # Проверка, настроен ли уже WireGuard
    if systemctl is-active --quiet wg-quick@wg0 2>/dev/null; then
        echo -e "${GREEN}✓${NC} WireGuard уже запущен"
        echo -e "${BLUE}Используется существующая конфигурация${NC}\n"
    else
        # Запуск скрипта установки клиента
        WG_CLIENT_SCRIPT="/opt/vpn-panel/wireguard_setup/install_wg_client.sh"
        
        if [ -f "$WG_CLIENT_SCRIPT" ]; then
            echo -e "${YELLOW}Запуск настройки WireGuard клиента...${NC}\n"
            bash "$WG_CLIENT_SCRIPT"
            
            if systemctl is-active --quiet wg-quick@wg0 2>/dev/null; then
                echo -e "\n${GREEN}✓${NC} WireGuard успешно настроен и запущен"
            else
                echo -e "${RED}✗${NC} Ошибка настройки WireGuard"
                echo -e "${RED}Невозможно продолжить без подключения к приватной сети${NC}"
                exit 1
            fi
        else
            echo -e "${RED}✗${NC} Скрипт $WG_CLIENT_SCRIPT не найден"
            echo -e "${RED}Невозможно продолжить без настройки WireGuard${NC}"
            exit 1
        fi
    fi
    
    # Определение хостов БД и Redis
    echo -e "\n${YELLOW}Определение хостов PostgreSQL и Redis...${NC}"
    ADMIN_PRIVATE_IP="10.0.0.1"  # Админка всегда на этом IP
    
    # Проверка PostgreSQL
    echo -e "${BLUE}Проверка доступности PostgreSQL...${NC}"
    PG_PORT=5432
    
    if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$ADMIN_PRIVATE_IP/$PG_PORT" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} PostgreSQL доступен на ${ADMIN_PRIVATE_IP}:${PG_PORT}"
        PG_HOST="$ADMIN_PRIVATE_IP"
    else
        echo -e "${YELLOW}⚠${NC}  PostgreSQL недоступен на стандартном порту $PG_PORT"
        
        while true; do
            read -p "Введите порт PostgreSQL на Admin сервере: " CUSTOM_PG_PORT
            
            if ! [[ "$CUSTOM_PG_PORT" =~ ^[0-9]+$ ]]; then
                echo -e "${RED}✗${NC} Порт должен быть числом"
                continue
            fi
            
            if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$ADMIN_PRIVATE_IP/$CUSTOM_PG_PORT" 2>/dev/null; then
                echo -e "${GREEN}✓${NC} PostgreSQL доступен на ${ADMIN_PRIVATE_IP}:${CUSTOM_PG_PORT}"
                PG_HOST="$ADMIN_PRIVATE_IP"
                PG_PORT="$CUSTOM_PG_PORT"
                break
            else
                echo -e "${RED}✗${NC} PostgreSQL недоступен на порту $CUSTOM_PG_PORT"
                read -p "Попробовать другой порт? (y/N): " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    echo -e "${RED}Невозможно продолжить без доступа к PostgreSQL${NC}"
                    exit 1
                fi
            fi
        done
    fi
    
    # Проверка Redis
    echo -e "\n${BLUE}Проверка доступности Redis...${NC}"
    REDIS_PORT=6379
    
    if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$ADMIN_PRIVATE_IP/$REDIS_PORT" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Redis доступен на ${ADMIN_PRIVATE_IP}:${REDIS_PORT}"
        REDIS_HOST="$ADMIN_PRIVATE_IP"
    else
        echo -e "${YELLOW}⚠${NC}  Redis недоступен на стандартном порту $REDIS_PORT"
        
        while true; do
            read -p "Введите порт Redis на Admin сервере: " CUSTOM_REDIS_PORT
            
            if ! [[ "$CUSTOM_REDIS_PORT" =~ ^[0-9]+$ ]]; then
                echo -e "${RED}✗${NC} Порт должен быть числом"
                continue
            fi
            
            if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$ADMIN_PRIVATE_IP/$CUSTOM_REDIS_PORT" 2>/dev/null; then
                echo -e "${GREEN}✓${NC} Redis доступен на ${ADMIN_PRIVATE_IP}:${CUSTOM_REDIS_PORT}"
                REDIS_HOST="$ADMIN_PRIVATE_IP"
                REDIS_PORT="$CUSTOM_REDIS_PORT"
                break
            else
                echo -e "${RED}✗${NC} Redis недоступен на порту $CUSTOM_REDIS_PORT"
                read -p "Попробовать другой порт? (y/N): " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    echo -e "${RED}Невозможно продолжить без доступа к Redis${NC}"
                    exit 1
                fi
            fi
        done
    fi
    
    echo -e "\n${GREEN}✓${NC} Все сервисы доступны:"
    echo -e "  PostgreSQL: ${BLUE}${PG_HOST}:${PG_PORT}${NC}"
    echo -e "  Redis: ${BLUE}${REDIS_HOST}:${REDIS_PORT}${NC}"
fi

# Интерактивный выбор домена для Sub Service
echo -e "\n${YELLOW}Настройка домена для Sub Service${NC}"
echo -e "${BLUE}Caddy будет использовать этот домен для HTTPS${NC}\n"

echo -e "${YELLOW}Варианты настройки:${NC}"
echo -e "  ${GREEN}1. localhost${NC} - для локального доступа (самоподписанный сертификат)"
echo -e "     Доступ: https://localhost"
echo -e "     ${YELLOW}⚠ Недоступно из интернета${NC}\n"

echo -e "  ${GREEN}2. Реальный домен${NC} - для доступа из интернета (Let's Encrypt сертификат)"
echo -e "     Пример: sub.example.com"
echo -e "     ${YELLOW}⚠ Требуется настройка DNS A-записи на IP этого сервера${NC}\n"

DEFAULT_SUB_DOMAIN="localhost"

# Если переменная SUB_DOMAIN задана (например, в CI), используем её
if [ -z "$SUB_DOMAIN" ]; then
    read -p "Введите домен для Sub Service (по умолчанию $DEFAULT_SUB_DOMAIN): " USER_DOMAIN
    SUB_DOMAIN=${USER_DOMAIN:-$DEFAULT_SUB_DOMAIN}
    
    # Валидация домена
    if [[ "$SUB_DOMAIN" =~ ^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$ ]] || [ "$SUB_DOMAIN" = "localhost" ]; then
        if [ "$SUB_DOMAIN" = "localhost" ]; then
            echo -e "${GREEN}✓${NC} Будет использован localhost (самоподписанный сертификат)"
            echo -e "${YELLOW}  Доступ только локально: https://localhost${NC}"
        else
            echo -e "${GREEN}✓${NC} Будет использован домен: $SUB_DOMAIN"
            echo -e "${YELLOW}  Убедитесь что DNS A-запись указывает на IP этого сервера${NC}"
            echo -e "${YELLOW}  Caddy автоматически получит Let's Encrypt сертификат${NC}"
        fi
    else
        echo -e "${RED}✗${NC} Некорректный домен"
        echo -e "${YELLOW}Установка отменена${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} Используется домен из переменной окружения: $SUB_DOMAIN"
fi

# Проверка портов 80 и 443 для Caddy
echo -e "\n${YELLOW}Проверка портов 80 и 443 для Caddy...${NC}"

PORT_80_BUSY=false
PORT_443_BUSY=false
CADDY_MODE="standalone"  # По умолчанию отдельный Caddy

# Проверяем порт 80
if lsof -Pi :80 -sTCP:LISTEN -t >/dev/null 2>&1; then
    PORT_80_BUSY=true
    echo -e "${YELLOW}⚠${NC}  Порт 80 занят"
fi

# Проверяем порт 443
if lsof -Pi :443 -sTCP:LISTEN -t >/dev/null 2>&1; then
    PORT_443_BUSY=true
    echo -e "${YELLOW}⚠${NC}  Порт 443 занят"
fi

# Если хотя бы один порт занят
if [ "$PORT_80_BUSY" = true ] || [ "$PORT_443_BUSY" = true ]; then
    echo -e "\n${YELLOW}Проверяем что занимает порты...${NC}"
    
    # Проверяем есть ли наш Caddy (caddy-admin)
    if docker ps --format '{{.Names}}' | grep -q '^caddy-admin$'; then
        echo -e "${GREEN}✓${NC} Найден Caddy от Admin Panel (caddy-admin)"
        echo -e "${BLUE}  Sub Service будет использовать общий Caddy${NC}"
        CADDY_MODE="shared"
    else
        # Порты заняты неизвестным процессом
        echo -e "${RED}✗${NC} Порты заняты другим процессом:"
        
        if [ "$PORT_80_BUSY" = true ]; then
            echo -e "\n${YELLOW}Процесс на порту 80:${NC}"
            lsof -Pi :80 -sTCP:LISTEN | head -5
        fi
        
        if [ "$PORT_443_BUSY" = true ]; then
            echo -e "\n${YELLOW}Процесс на порту 443:${NC}"
            lsof -Pi :443 -sTCP:LISTEN | head -5
        fi
        
        echo -e "\n${RED}Освободите порты 80 и 443 или остановите Admin Panel Caddy перед установкой Sub Service${NC}"
        echo -e "${YELLOW}Установка отменена${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} Порты 80 и 443 свободны"
    echo -e "${BLUE}  Sub Service будет использовать отдельный Caddy${NC}"
fi

# Путь к .env файлу
ENV_SUB_FILE="$SUB_DIR/.env.sub.prod"

# Создание .env.sub.prod
echo -e "\n${YELLOW}Создание конфигурации Sub Service...${NC}"

cat > "$ENV_SUB_FILE" <<ENVEOF
# PostgreSQL (используется из web admin через WireGuard)
PG_USER=reinar_crud_user
PG_PASSWORD=VjZ0ChrfMfp9!
PG_DB=reinar_db
PG_HOST=${PG_HOST}
PG_PORT=${PG_PORT}
PG_MAX_CONNECTIONS=50

# Redis (используется из web admin через WireGuard)
REDIS_PASSWORD=R'F&scBdorS8@0A-1!
REDIS_MAX_CONNECTIONS=50
REDIS_HOST=${REDIS_HOST}
REDIS_PORT=${REDIS_PORT}

# Application
UVICORN_WORKERS=1
POST_PROCESSING_RESPONSES=1
UVICORN_PORT=${SUB_PORT}
TRUSTED_PROXIES=127.0.0.1,10.0.0.1
DOMAIN=https://${SUB_DOMAIN}

# Robokassa
ROBO_SHOP_LOGIN=${ROBO_SHOP_LOGIN}
ROBO_CRYPT_ALGORITHM=sha256
ROBO_PASSW_1=${ROBO_PASSW_1}
ROBO_PASSW_2=${ROBO_PASSW_2}

# ARQ Settings (должны совпадать с web admin)
ARQ_QUEUE_NAME=arq:cron_background_queue
ARQ_MAX_JOBS=10
ARQ_JOB_TIMEOUT=300
ACTION_ON_CORE_PROTO_LIMIT=10

# Subscription settings
# Длина строки для подписок. Увеличить, если новые пользователи вставляются с 3-4 раза. Макс 64
SUB_LINK_BYTES=32
# Указывать только числа в часах
SUBSCRIPTION_UPDATE_INTERVAL=12

# Telegram Bot
TG_BOT_LINK=https://t.me/BotFather
TG_BOT_SERVICE_PRIVATE_IP=10.0.0.2,127.0.0.1
# TG_BOT_TOKEN можно настроить позже
# TG_BOT_TOKEN=your_bot_token_here

# App Mode
APP_MODE=prod
PAY_MODE=test
ENVEOF

echo -e "${GREEN}✓${NC} Конфигурация создана: $ENV_SUB_FILE"


# Обновление .env для docker-compose (добавление SUB_PORT и SUB_DOMAIN)
echo -e "\n${YELLOW}Обновление .env для Docker Compose...${NC}"
ENV_FILE="$INSTALL_DIR/.env"

if grep -q "^SUB_PORT=" "$ENV_FILE"; then
    sed -i "s/^SUB_PORT=.*/SUB_PORT=${SUB_PORT}/" "$ENV_FILE"
else
    echo "SUB_PORT=${SUB_PORT}" >> "$ENV_FILE"
fi

if grep -q "^SUB_DOMAIN=" "$ENV_FILE"; then
    sed -i "s/^SUB_DOMAIN=.*/SUB_DOMAIN=${SUB_DOMAIN}/" "$ENV_FILE"
else
    echo "SUB_DOMAIN=${SUB_DOMAIN}" >> "$ENV_FILE"
fi

echo -e "${GREEN}✓${NC} .env обновлён"

# Подготовка директорий логов для sub-сервиса
echo -e "\n${YELLOW}Подготовка директорий логов...${NC}"
mkdir -p "$SUB_DIR/sub_logs"
chmod -R 777 "$SUB_DIR/sub_logs"
echo -e "${GREEN}✓${NC} Директории логов подготовлены"

# Создание .env для docker-compose (только для standalone mode)
if [ "$CADDY_MODE" = "standalone" ]; then
    echo -e "\n${YELLOW}Создание .env для Docker Compose...${NC}"
    ENV_COMPOSE_FILE="$SUB_DIR/.env"
    
    cat > "$ENV_COMPOSE_FILE" <<ENVEOF
SUB_DOMAIN=${SUB_DOMAIN}
SUB_PORT=${SUB_PORT}
ENVEOF
    
    echo -e "${GREEN}✓${NC} .env создан: $ENV_COMPOSE_FILE"
fi

# Настройка Caddy в зависимости от режима
if [ "$CADDY_MODE" = "shared" ]; then
    echo -e "\n${YELLOW}Настройка общего Caddy (shared mode)...${NC}"
    
    # Проверяем что домены не совпадают
    ADMIN_DOMAIN=$(grep "^ADMIN_DOMAIN=" "$ENV_FILE" | cut -d'=' -f2)
    
    if [ -n "$ADMIN_DOMAIN" ] && [ "$SUB_DOMAIN" = "$ADMIN_DOMAIN" ]; then
        echo -e "${RED}✗${NC} Ошибка: В shared mode нельзя использовать одинаковый домен для Admin и Sub Service"
        echo -e "${YELLOW}  Admin Panel использует домен: ${ADMIN_DOMAIN}${NC}"
        echo -e "${YELLOW}  Caddy не поддерживает дублирующие директивы доменов${NC}"
        echo -e "${YELLOW}  Укажите другой домен для Sub Service${NC}"
        echo -e "${YELLOW}Установка отменена${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓${NC} Домены не конфликтуют (Admin: ${ADMIN_DOMAIN}, Sub: ${SUB_DOMAIN})"
    
    # Раскомментируем строку с sub.caddy в docker-compose.admin.yml
    ADMIN_COMPOSE="$INSTALL_DIR/docker-compose.admin.yml"
    
    if grep -q "^#      - ./sub/sub.caddy:/etc/caddy/conf.d/sub.caddy" "$ADMIN_COMPOSE"; then
        sed -i 's|^#      - ./sub/sub.caddy:/etc/caddy/conf.d/sub.caddy|      - ./sub/sub.caddy:/etc/caddy/conf.d/sub.caddy|' "$ADMIN_COMPOSE"
        echo -e "${GREEN}✓${NC} Конфигурация sub.caddy добавлена в caddy-admin"
    else
        echo -e "${YELLOW}⚠${NC}  Конфигурация sub.caddy уже активна"
    fi
    
    echo -e "${GREEN}✓${NC} Caddy настроен в shared mode"
fi

# Перезапуск Docker Compose
echo -e "\n${YELLOW}Запуск Sub Service...${NC}"
cd "$SUB_DIR"

# Запускаем sub-service
if [ "$CADDY_MODE" = "standalone" ]; then
    # Запускаем с отдельным Caddy
    docker compose -f docker-compose.caddy.yml up -d --build
    echo -e "${GREEN}✓${NC} Sub Service запущен с отдельным Caddy"
else
    # Запускаем только sub-service (без Caddy)
    docker compose -f docker-compose.yml up -d --build
    echo -e "${GREEN}✓${NC} Sub Service запущен"
    
    # Перезапускаем caddy-admin для применения новой конфигурации
    echo -e "\n${YELLOW}Перезапуск Caddy для применения конфигурации...${NC}"
    cd "$INSTALL_DIR"
    docker compose -f docker-compose.admin.yml up -d caddy
    echo -e "${GREEN}✓${NC} Caddy перезапущен с новыми переменными окружения"
fi

# Финальное сообщение
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Установка завершена успешно!${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Формируем URL в зависимости от домена
if [ "$SUB_DOMAIN" = "localhost" ]; then
    SERVICE_URL="https://localhost"
    echo -e "${YELLOW}⚠  Используется самоподписанный сертификат${NC}"
    echo -e "${YELLOW}   Браузер покажет предупреждение о безопасности - это нормально${NC}"
    echo -e "${YELLOW}   Сервис доступен только локально${NC}\n"
else
    SERVICE_URL="https://${SUB_DOMAIN}"
    echo -e "${GREEN}✓${NC} Let's Encrypt сертификат будет получен автоматически"
    echo -e "${YELLOW}  Убедитесь что DNS A-запись для ${SUB_DOMAIN} указывает на IP этого сервера${NC}\n"
fi

echo -e "Sub Service доступен по адресу: ${GREEN}${SERVICE_URL}${NC}"

if [ "$CADDY_MODE" = "shared" ]; then
    echo -e "${BLUE}Режим: Shared Caddy (использует caddy-admin)${NC}\n"
    
    echo -e "${YELLOW}Управление сервисами:${NC}"
    echo -e "  Sub Service:"
    echo -e "    Директория:  ${BLUE}cd $SUB_DIR${NC}"
    echo -e "    Статус:      ${BLUE}docker compose ps${NC}"
    echo -e "    Остановка:   ${BLUE}docker compose down${NC}"
    echo -e "    Запуск:      ${BLUE}docker compose up -d${NC}"
    echo -e "    Перезапуск:  ${BLUE}docker compose restart sub-service${NC}"
    echo -e "    Логи:        ${BLUE}docker compose logs -f sub-service${NC}\n"
    
    echo -e "  Caddy (управляется через Admin Panel):"
    echo -e "    Директория:  ${BLUE}cd $INSTALL_DIR${NC}"
    echo -e "    Перезапуск:  ${BLUE}docker compose -f docker-compose.admin.yml restart caddy${NC}"
    echo -e "    Логи:        ${BLUE}docker compose -f docker-compose.admin.yml logs -f caddy${NC}\n"
else
    echo -e "${BLUE}Режим: Standalone Caddy (отдельный контейнер caddy-sub)${NC}\n"
    
    echo -e "${YELLOW}Управление сервисами:${NC}"
    echo -e "  Директория:  ${BLUE}cd $SUB_DIR${NC}"
    echo -e "  Статус:      ${BLUE}docker compose -f docker-compose.caddy.yml ps${NC}"
    echo -e "  Остановка:   ${BLUE}docker compose -f docker-compose.caddy.yml down${NC}"
    echo -e "  Запуск:      ${BLUE}docker compose -f docker-compose.caddy.yml up -d${NC}"
    echo -e "  Перезапуск Sub:   ${BLUE}docker compose -f docker-compose.caddy.yml restart sub-service${NC}"
    echo -e "  Перезапуск Caddy: ${BLUE}docker compose -f docker-compose.caddy.yml restart caddy${NC}"
    echo -e "  Логи Sub:    ${BLUE}docker compose -f docker-compose.caddy.yml logs -f sub-service${NC}"
    echo -e "  Логи Caddy:  ${BLUE}docker compose -f docker-compose.caddy.yml logs -f caddy${NC}\n"
fi

echo -e "${YELLOW}Конфигурация:${NC}"
echo -e "  Sub Service:    ${BLUE}$ENV_SUB_FILE${NC}"
echo -e "  Docker Compose: ${BLUE}$INSTALL_DIR/.env${NC}\n"

echo -e "${YELLOW}Следующие шаги:${NC}"
echo -e "  1.1. Настройте Robokassa в личном кабинете (https://login.robokassa.ru/)"
echo -e "  1.2. Подставьте логин и пароли в ROBO переменные (/opt/reinar_panel/web/sub/.env.sub.prod)"
echo -e "  2. Настройте Telegram бота. Получите токен в @BotFather, подключите бота"

