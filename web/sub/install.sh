#!/bin/bash

set -e  # Выход при ошибке

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Константы
INSTALL_BASE="/opt/vpn-panel"
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

# Проверка что web уже установлен
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}✗${NC} Web Admin Panel не установлен"
    echo "Сначала установите web: cd /opt/vpn-panel/web && sudo bash install.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} Web Admin Panel найден"

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

# Запрос Robokassa credentials
echo -e "\n${YELLOW}Настройка Robokassa${NC}"
echo -e "${BLUE}Для работы платёжной системы требуются данные от Robokassa${NC}"

read -p "Введите Robokassa Shop Login: " ROBO_SHOP_LOGIN
read -p "Введите Robokassa Password 1: " ROBO_PASSW_1
read -p "Введите Robokassa Password 2: " ROBO_PASSW_2

# Запрос Telegram Bot Link
echo -e "\n${YELLOW}Настройка Telegram Bot${NC}"
DEFAULT_TG_BOT="https://t.me/your_bot"
read -p "Введите ссылку на Telegram бота (по умолчанию $DEFAULT_TG_BOT): " TG_BOT_LINK
TG_BOT_LINK=${TG_BOT_LINK:-$DEFAULT_TG_BOT}

# Путь к .env файлу
ENV_SUB_FILE="$SUB_DIR/.env.sub.prod"

# Создание .env.sub.prod
echo -e "\n${YELLOW}Создание конфигурации Sub Service...${NC}"

cat > "$ENV_SUB_FILE" <<ENVEOF
# PostgreSQL (используется из web)
PG_USER=reinar_crud_user
PG_PASSWORD=VjZ0ChrfMfp9!
PG_DB=reinar_db
PG_HOST=127.0.0.1
PG_PORT=5432
PG_MAX_CONNECTIONS=50

# Redis (используется из web)
REDIS_PASSWORD=R'F&scBdorS8@0A-1!
REDIS_MAX_CONNECTIONS=50
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# Application
UVICORN_WORKERS=1
POST_PROCESSING_RESPONSES=1
UVICORN_PORT=${SUB_PORT}

# Robokassa
ROBO_SHOP_LOGIN=${ROBO_SHOP_LOGIN}
ROBO_CRYPT_ALGORITHM=sha256
ROBO_PASSW_1=${ROBO_PASSW_1}
ROBO_PASSW_2=${ROBO_PASSW_2}

# ARQ Settings
ARQ_QUEUE_NAME=arq:sub_queue
ARQ_MAX_JOBS=10
ARQ_JOB_TIMEOUT=300

# Subscription settings
ACTION_ON_CORE_PROTO_LIMIT=10
SUBSCRIPTION_UPDATE_INTERVAL=12

# Telegram Bot
TG_BOT_LINK=${TG_BOT_LINK}

# App Mode
APP_MODE=docker
ENVEOF

echo -e "${GREEN}✓${NC} Конфигурация создана: $ENV_SUB_FILE"

# Обновление docker-compose.yml (раскомментирование include)
echo -e "\n${YELLOW}Обновление docker-compose.yml...${NC}"
COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"

if [ -f "$COMPOSE_FILE" ]; then
    # Раскомментируем строчку с sub/docker-compose.yml
    sed -i 's/^  # - sub\/docker-compose\.yml$/  - sub\/docker-compose.yml/' "$COMPOSE_FILE"
    echo -e "${GREEN}✓${NC} docker-compose.yml обновлён"
else
    echo -e "${RED}✗${NC} docker-compose.yml не найден: $COMPOSE_FILE"
    exit 1
fi

# Обновление .env для docker-compose (добавление SUB_PORT)
echo -e "\n${YELLOW}Обновление .env для Docker Compose...${NC}"
ENV_FILE="$INSTALL_DIR/.env"

if grep -q "^SUB_PORT=" "$ENV_FILE"; then
    sed -i "s/^SUB_PORT=.*/SUB_PORT=${SUB_PORT}/" "$ENV_FILE"
else
    echo "SUB_PORT=${SUB_PORT}" >> "$ENV_FILE"
fi

echo -e "${GREEN}✓${NC} .env обновлён"

# Перезапуск Docker Compose
echo -e "\n${YELLOW}Перезапуск Docker Compose...${NC}"
cd "$INSTALL_DIR"

# Останавливаем текущие контейнеры
docker compose -f /opt/vpn-panel/web/docker-compose.yml down

# Запускаем с новой конфигурацией
docker compose up -d --build

# Ожидание запуска
echo -e "\n${YELLOW}Ожидание запуска сервисов...${NC}"
sleep 5

# Проверка статуса
if docker compose ps | grep -q "sub-service.*Up"; then
    echo -e "${GREEN}✓${NC} Sub Service успешно запущен"
else
    echo -e "${RED}✗${NC} Ошибка запуска Sub Service"
    echo "Проверьте логи: cd $INSTALL_DIR && docker compose logs sub-service"
    exit 1
fi

# Финальное сообщение
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Установка завершена успешно!${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "Sub Service доступен по адресу: ${GREEN}http://localhost:${SUB_PORT}${NC}"
echo -e "Swagger документация: ${GREEN}http://localhost:${SUB_PORT}/docs${NC}\n"

echo -e "${YELLOW}Управление сервисами:${NC}"
echo -e "  Перейти в директорию: ${BLUE}cd $INSTALL_DIR${NC}"
echo -e "  Статус:      ${BLUE}docker compose ps${NC}"
echo -e "  Остановка:   ${BLUE}docker compose down${NC}"
echo -e "  Запуск:      ${BLUE}docker compose up -d${NC}"
echo -e "  Перезапуск:  ${BLUE}docker compose restart sub-service arq-sub-worker${NC}"
echo -e "  Логи Sub:    ${BLUE}docker compose logs -f sub-service${NC}"
echo -e "  Логи ARQ:    ${BLUE}docker compose logs -f arq-sub-worker${NC}\n"

echo -e "${YELLOW}Конфигурация:${NC}"
echo -e "  Sub Service: ${BLUE}$ENV_SUB_FILE${NC}\n"

echo -e "${YELLOW}Следующие шаги:${NC}"
echo -e "  1. Настройте Robokassa в личном кабинете"
echo -e "  2. Настройте Telegram бота"
echo -e "  3. Проверьте работу платёжной системы\n"
