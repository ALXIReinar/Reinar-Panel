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

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  VPN Admin Panel - Установка${NC}"
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

# Проверка наличия необходимых файлов
echo -e "\n${YELLOW}Проверка исходных файлов...${NC}"
REQUIRED_FILES=("docker-compose.server.yml" "Dockerfile" "requirements.txt" "main.py")
REQUIRED_DIRS=("api" "config_dir" "data" "schemas" "utils" "secrets")

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$SCRIPT_DIR/$file" ]; then
        echo -e "${RED}✗${NC} Файл не найден: $file"
        echo "Убедитесь, что скрипт запущен из директории web/"
        exit 1
    fi
done

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ ! -d "$SCRIPT_DIR/$dir" ]; then
        echo -e "${RED}✗${NC} Директория не найдена: $dir"
        echo "Убедитесь, что скрипт запущен из директории web/"
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

# Интерактивный выбор порта для админ-панели
echo -e "\n${YELLOW}Настройка порта для Admin Panel${NC}"
DEFAULT_PORT=8000

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

# Запрос приватного IP для WireGuard
echo -e "\n${YELLOW}Настройка WireGuard приватной сети${NC}"
DEFAULT_WG_IP="10.0.0.1"

read -p "Введите приватный IP админ-панели для WireGuard (по умолчанию $DEFAULT_WG_IP): " WG_PRIVATE_IP
WG_PRIVATE_IP=${WG_PRIVATE_IP:-$DEFAULT_WG_IP}

echo -e "${GREEN}✓${NC} WireGuard приватный IP: $WG_PRIVATE_IP"

# Создание директории установки
echo -e "\n${YELLOW}Создание директории ${INSTALL_DIR}...${NC}"
mkdir -p "$INSTALL_DIR"
echo -e "${GREEN}✓${NC} Директория создана"

# Копирование файлов
echo -e "\n${YELLOW}Копирование файлов приложения...${NC}"

# Копируем всю структуру web/ в /opt/vpn-panel/admin/
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true

# Убедимся, что скрипты установки не попали в production
rm -f "$INSTALL_DIR/install.sh" 2>/dev/null || true

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

# Генерация RSA ключей для JWT
echo -e "\n${YELLOW}Генерация RSA ключей для JWT...${NC}"
KEYS_DIR="$INSTALL_DIR/secrets/keys"
mkdir -p "$KEYS_DIR"

if [ ! -f "$KEYS_DIR/private_key.pem" ] || [ ! -f "$KEYS_DIR/public_key.pem" ]; then
    # Генерация приватного ключа
    openssl genrsa -out "$KEYS_DIR/private_key.pem" 2048
    # Генерация публичного ключа из приватного
    openssl rsa -in "$KEYS_DIR/private_key.pem" -outform PEM -pubout -out "$KEYS_DIR/public_key.pem"
    
    # Установка прав
    chmod 600 "$KEYS_DIR/private_key.pem"
    chmod 644 "$KEYS_DIR/public_key.pem"
    
    echo -e "${GREEN}✓${NC} RSA ключи сгенерированы"
else
    echo -e "${GREEN}✓${NC} RSA ключи уже существуют, пропускаем генерацию"
fi

# Путь к .env файлам
ENV_FILE="$INSTALL_DIR/.env"
ENV_API_FILE="$INSTALL_DIR/.env.api.prod"

# Создание или обновление .env файла для docker-compose
echo -e "\n${YELLOW}Настройка конфигурации Docker Compose...${NC}"

cat > "$ENV_FILE" <<ENVEOF
# Docker Compose Configuration
# Для работы docker compose healthcheck. Убедитесь, что в .env.api.prod эти переменные идентичны
ADMIN_PORT=${ADMIN_PORT}

# PostgreSQL
PG_DB=reinar_db
PG_ADMIN=postgres
PG_ADMIN_PASSWORD=(AD^9cya97tCA*9ouhCAksb!
ENVEOF

echo -e "${GREEN}✓${NC} Конфигурация Docker Compose создана: $ENV_FILE"

# Создание или обновление .env.api.prod для приложения
echo -e "\n${YELLOW}Настройка конфигурации приложения...${NC}"

if [ ! -f "$ENV_API_FILE" ]; then
    cat > "$ENV_API_FILE" <<APIENVEOF
# Application Configuration
ADMIN_PORT=${ADMIN_PORT}
UVI_WORKERS=1
APP_MODE=docker
DOMAIN=http://localhost:${ADMIN_PORT}
POST_PROCESSING_RESPONSES=1

REDIS_PASSWORD=R'F&scBdorS8@0A-1!
REDIS_MAX_CONNECTIONS=50
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_HOST_DOCKER=redis
REDIS_PORT_DOCKER=6379


# PostgreSQL (НЕ МЕНЯТЬ - вшито в скрипты инициализации БД!)
PG_USER=reinar_crud_user
PG_PASSWORD=VjZ0ChrfMfp9!
PG_DB=reinar_db
PG_HOST=127.0.0.1
PG_PORT=5432
PG_HOST_DOCKER=localhost
PG_PORT_DOCKER=5432
PG_MAX_CONNECTIONS=50

# WireGuard
ADMIN_PRIVATE_IP=${WG_PRIVATE_IP}
APIENVEOF
    echo -e "${GREEN}✓${NC} Конфигурация приложения создана: $ENV_API_FILE"
else
    echo -e "${YELLOW}Обновление существующего .env.api.prod...${NC}"
    
    # Обновляем UVI_PORT
    if grep -q "^UVI_PORT=" "$ENV_API_FILE"; then
        sed -i "s/^UVI_PORT=.*/UVI_PORT=${ADMIN_PORT}/" "$ENV_API_FILE"
    else
        echo "UVI_PORT=${ADMIN_PORT}" >> "$ENV_API_FILE"
    fi
    
    # Обновляем ADMIN_PRIVATE_IP
    if grep -q "^ADMIN_PRIVATE_IP=" "$ENV_API_FILE"; then
        sed -i "s/^ADMIN_PRIVATE_IP=.*/ADMIN_PRIVATE_IP=${WG_PRIVATE_IP}/" "$ENV_API_FILE"
    else
        echo "ADMIN_PRIVATE_IP=${WG_PRIVATE_IP}" >> "$ENV_API_FILE"
    fi
    
    echo -e "${GREEN}✓${NC} Конфигурация приложения обновлена"
fi

# Экспорт переменной для docker compose
export ADMIN_PORT

# Остановка существующих контейнеров
echo -e "\n${YELLOW}Остановка существующих контейнеров...${NC}"
cd "$INSTALL_DIR"
docker compose -f docker-compose.server.yml down 2>/dev/null || true
echo -e "${GREEN}✓${NC} Контейнеры остановлены"

# Сборка и запуск
echo -e "\n${YELLOW}Сборка и запуск контейнеров...${NC}"
docker compose -f docker-compose.server.yml up -d --build

# Ожидание запуска
echo -e "\n${YELLOW}Ожидание запуска сервисов...${NC}"
sleep 5

# Проверка статуса
if docker compose -f docker-compose.server.yml ps | grep -q "Up"; then
    echo -e "${GREEN}✓${NC} Контейнеры успешно запущены"
else
    echo -e "${RED}✗${NC} Ошибка запуска контейнеров"
    echo "Проверьте логи: cd $INSTALL_DIR && docker compose -f docker-compose.server.yml logs"
    exit 1
fi

# Финальное сообщение
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Установка завершена успешно!${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "Директория установки: ${GREEN}${INSTALL_DIR}${NC}"
echo -e "Admin Panel доступна по адресу: ${GREEN}http://localhost:${ADMIN_PORT}${NC}"
echo -e "WireGuard приватный IP: ${GREEN}${WG_PRIVATE_IP}${NC}\n"

echo -e "${YELLOW}Управление сервисами:${NC}"
echo -e "  Перейти в директорию: ${BLUE}cd $INSTALL_DIR${NC}"
echo -e "  Статус:      ${BLUE}docker compose -f docker-compose.server.yml ps${NC}"
echo -e "  Остановка:   ${BLUE}docker compose -f docker-compose.server.yml down${NC}"
echo -e "  Запуск:      ${BLUE}docker compose -f docker-compose.server.yml up -d${NC}"
echo -e "  Перезапуск:  ${BLUE}docker compose -f docker-compose.server.yml restart${NC}"
echo -e "  Логи:        ${BLUE}docker compose -f docker-compose.server.yml logs -f${NC}\n"

echo -e "${YELLOW}Конфигурация:${NC}"
echo -e "  Docker Compose: ${BLUE}$ENV_FILE${NC}"
echo -e "  Приложение:     ${BLUE}$ENV_API_FILE${NC}"
echo -e "  RSA ключи:      ${BLUE}$INSTALL_DIR/secrets/keys/${NC}\n"

echo -e "${YELLOW}Следующие шаги:${NC}"
echo -e "  1. Настройте WireGuard для приватной сети между серверами"
echo -e "  2. Установите Node Client: ${BLUE}cd /path/to/node_client && sudo bash install.sh${NC}"
echo -e "  3. Добавьте ноды через Admin Panel\n"
