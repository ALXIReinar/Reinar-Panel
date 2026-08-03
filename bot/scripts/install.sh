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
INSTALL_DIR="$INSTALL_BASE/bot"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Reinar Telegram Bot - Установка${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Проверка прав root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Скрипт должен быть запущен с правами root${NC}"
   echo "Используйте: sudo bash install.sh"
   exit 1
fi

echo -e "${GREEN}✓${NC} Права root подтверждены"

# Определение директории скрипта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Скрипт находится в bot/scripts/, поднимаемся на уровень выше в bot/
BOT_DIR="$(dirname "$SCRIPT_DIR")"

# Проверка наличия необходимых файлов
echo -e "\n${YELLOW}Проверка исходных файлов...${NC}"
REQUIRED_FILES=("docker-compose.yml" "Dockerfile" "requirements.txt" "pytest.ini")
REQUIRED_DIRS=("core" "config_dir" "tests")

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$BOT_DIR/$file" ]; then
        echo -e "${RED}✗${NC} Файл не найден: $file"
        echo "Убедитесь, что структура проекта корректна"
        exit 1
    fi
done

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ ! -d "$BOT_DIR/$dir" ]; then
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

# Создание директории установки
echo -e "\n${YELLOW}Создание директории ${INSTALL_DIR}...${NC}"
mkdir -p "$INSTALL_DIR"
echo -e "${GREEN}✓${NC} Директория создана"

# Копирование файлов
echo -e "\n${YELLOW}Копирование файлов приложения...${NC}"

# Копируем всю структуру bot/ в /opt/reinar_panel/bot/
cp -r "$BOT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true

echo -e "${GREEN}✓${NC} Файлы скопированы"

# Установка правильных прав
echo -e "\n${YELLOW}Установка прав доступа...${NC}"
chmod -R 755 "$INSTALL_DIR"
echo -e "${GREEN}✓${NC} Права установлены"

# Путь к .env файлам
ENV_FILE="$INSTALL_DIR/.env"
ENV_BOT_FILE="$INSTALL_DIR/.env.bot.prod"

# Функция для интерактивного/CI-совместимого ввода
read_with_default() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    local current_value="${!var_name}"
    
    # Если переменная уже задана в окружении (CI), используем её
    if [ -n "$current_value" ]; then
        echo -e "${GREEN}✓${NC} Используется значение из окружения для $var_name: $current_value"
        eval "$var_name='$current_value'"
        return
    fi
    
    # Интерактивный режим
    read -p "$prompt [$default]: " input
    eval "$var_name=\${input:-$default}"
}

# Интерактивный сбор данных или использование переменных из окружения
echo -e "\n${YELLOW}Настройка конфигурации Telegram Bot${NC}"
echo -e "${BLUE}Если переменные уже заданы в окружении (CI), они будут использованы автоматически${NC}\n"

# BOT_TOKEN
if [ -z "$BOT_TOKEN" ]; then
    while true; do
        read -p "Введите BOT_TOKEN (от @BotFather): " BOT_TOKEN
        if [ -z "$BOT_TOKEN" ]; then
            echo -e "${RED}✗${NC} BOT_TOKEN не может быть пустым"
            continue
        fi
        # Проверка формата токена (примерно: 123456789:ABCDEF...)
        if [[ ! "$BOT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
            echo -e "${RED}✗${NC} Неверный формат BOT_TOKEN"
            echo "Формат должен быть: 123456789:ABCDEF..."
            continue
        fi
        break
    done
else
    echo -e "${GREEN}✓${NC} Используется BOT_TOKEN из окружения"
fi

# SUB_SERVICE_URL
DEFAULT_SUB_URL="http://10.0.0.2:8080"
read_with_default "Введите SUB_SERVICE_URL (Пример: http://10.0.0.2:8080)" "$DEFAULT_SUB_URL" "SUB_SERVICE_URL"

# ADMIN_TG_ID
if [ -z "$ADMIN_TG_ID" ]; then
    while true; do
        read -p "Введите ADMIN_TG_ID (Telegram ID администратора): " ADMIN_TG_ID
        if [ -z "$ADMIN_TG_ID" ]; then
            echo -e "${RED}✗${NC} ADMIN_TG_ID не может быть пустым"
            continue
        fi
        # Проверка что это число
        if ! [[ "$ADMIN_TG_ID" =~ ^[0-9]+$ ]]; then
            echo -e "${RED}✗${NC} ADMIN_TG_ID должен быть числом"
            continue
        fi
        break
    done
else
    echo -e "${GREEN}✓${NC} Используется ADMIN_TG_ID из окружения: $ADMIN_TG_ID"
fi

# Redis настройки

DEFAULT_REDIS_PASSWORD=$(openssl rand -base64 24 | tr -d "=+/" | cut -c1-20)


if [ -z "$REDIS_PASSWORD" ]; then
    echo -e "${YELLOW}Генерация безопасного пароля для Redis...${NC}"
    REDIS_PASSWORD="$DEFAULT_REDIS_PASSWORD"
    echo -e "${GREEN}✓${NC} Пароль сгенерирован: $REDIS_PASSWORD"
else
    echo -e "${GREEN}✓${NC} Используется REDIS_PASSWORD из окружения"
fi

# Создание .env файла для docker-compose
echo -e "\n${YELLOW}Создание конфигурации Docker Compose...${NC}"

cat > "$ENV_FILE" <<ENVEOF
# Docker Compose Configuration for Telegram Bot

# Redis
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_PORT=6379
ENVEOF

echo -e "${GREEN}✓${NC} Конфигурация Docker Compose создана: $ENV_FILE"

# Создание .env.bot.prod для приложения
echo -e "\n${YELLOW}Создание конфигурации бота...${NC}"

cat > "$ENV_BOT_FILE" <<BOTENVEOF
# Telegram Bot Configuration
BOT_TOKEN=${BOT_TOKEN}

# Redis
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_MAX_CONNECTIONS=50
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# Rate Limiting
USER_REQ_LIMIT=50
USER_REQ_WINDOW_SECONDS=60
SHOP_SUB_PLANS_TTL=3600

# Subscription Service
SUB_SERVICE_URL=${SUB_SERVICE_URL}
ADMIN_TG_ID=${ADMIN_TG_ID}
APP_MODE=docker

# Message Templates
MESSAGE_START='
🛡 Добро пожаловать в VPN!

VPN Который надёжный, безопасный и т.д.

👤 Ваш аккаунт, <b>{USER_TG_FIRST_NAME} {USER_TG_LAST_NAME}</b>:

🆔 ID: <code>{USER_TG_ID}</code>
🕘 Дата регистрации в боте: <b>{USER_REGISTERED_DATE}</b>
📦 Подписок на аккаунте: <b>{USER_SUB_COUNT}</b>

👇 Выберите нужный раздел в меню ниже.
'
MESSAGE_PROFILE='
👤 <b>Личный кабинет</b>

Добро пожаловать, <b>{USER_TG_USERNAME}</b>!

📦 Подписок на аккаунте: <b>{USER_SUB_COUNT}</b>

🕘 Дата регистрации в боте: {USER_REGISTERED_DATE}


👇 Выберите нужный раздел.
'
MESSAGE_ABOUT='
🔗 <b>Наши ссылки</b>

🛡  <a href="https://google.com">Ссылка на тг канал</a>

📄 <a href="https://google.com">Пользовательское соглашение</a>
🔒 <a href="https://google.com">Политика конфиденциальности</a>
'
MESSAGE_SUBSCRIPTIONS_SHOP_INTRO='
💎 <b>Управление подписками</b>

В этом разделе вы можете:

🔄 Продлить действующие подписки.
➕ Приобрести новые подписки VPN.

👇 Выберите нужное действие.
'
MESSAGE_SUBSCRIPTIONS_SHOP_EXTENT='
<b>{SUB_TITLE}</b>

🔐 О подписке
{SUB_DESCRIPTION}

🌐 Количество локаций для покдлючения: <b>{SUB_NODES_COUNT}</b>

📱 Устройства неограничены

👇 Выберите тариф
'
MESSAGE_USER_PROFILE_SUBS_INTRO='
В этом разделе отображаются все ваши активные и завершенные подписки.

Здесь вы можете посмотреть детали каждой подписки и при необходимости продлить

👇 Выберите нужную подписку ниже. Используйте "<" и ">"
'
MESSAGE_SUBSCRIPTIONS_USER_EXTENT='
<b>{USER_SUB_TITLE}</b>

<code>{USER_SUB_LINK}</code>

{USER_SUB_STATUS}

📊 Трафик. Использовано/Доступно
Сегодня: <b>{USER_SUB_TRAFFIC_USED_DAY}GB</b>/<b>{USER_SUB_TRAFFIC_LIMIT_DAY}GB</b>
Всего: <b>{USER_SUB_TRAFFIC_USED}GB</b>/<b>{USER_SUB_TRAFFIC_LIMIT}GB</b>

⏳ Срок действия до: <b>{USER_SUB_EXPIRE_DATE}</b>
Дата покупки: <b>{USER_SUB_CREATED_AT}</b>

📱 Устройства неограничены
'
MESSAGE_SUBSCRIPTIONS_OFFERS_INTRO='
💎 Продление подписки:

<code>{USER_SUB_LINK}</code>

Текущий срок действия:
⏳ До <b>{USER_SUB_EXPIRE_DATE}</b>

📱 Устройства неограничены

👇 Выберите период продления.
'
MESSAGE_SUBSCRIPTIONS_OFFERS_EXTENT='
{SUB_COST}₽ / {SUB_TTL_DAYS} дней / {SUB_TRAFFIC_LIMIT_DAY} GB/день / {SUB_TRAFFIC_LIMIT} GB
'
MESSAGE_PAY_WINDOW='
⚡️ Оплата действительна в течение 15 минут

Тарифный план: <b>{SUB_TITLE}</b>

Сумма: <b>{PAY_AMOUNT}</b> ₽

Нажмите кнопку «Оплатить» для перехода на страницу оплаты.

⚙️ После успешной оплаты вы автоматически получите ссылку для подключения
'
MESSAGE_HELP='
🆘 За помощью обращаться в @our_vpn_provider_support
'
BOTENVEOF

echo -e "${GREEN}✓${NC} Конфигурация бота создана: $ENV_BOT_FILE"

# Подготовка директорий логов с правильными правами
echo -e "\n${YELLOW}Подготовка директорий логов...${NC}"
mkdir -p "$INSTALL_DIR/bot_logs"
chmod -R 777 "$INSTALL_DIR/bot_logs"
echo -e "${GREEN}✓${NC} Директории логов подготовлены"

# Остановка существующих контейнеров
echo -e "\n${YELLOW}Остановка существующих контейнеров...${NC}"
cd "$INSTALL_DIR"
docker compose down 2>/dev/null || true
echo -e "${GREEN}✓${NC} Контейнеры остановлены"

# Сборка и запуск
echo -e "\n${YELLOW}Сборка и запуск контейнеров...${NC}"
echo -e "${BLUE}Рабочая директория: $INSTALL_DIR${NC}"
echo -e "${BLUE}Выполняется: docker compose up -d --build${NC}"

# Запускаем с полным выводом для диагностики
if ! docker compose up -d --build 2>&1 | tee /tmp/docker_compose_output.log; then
    echo -e "\n${RED}✗${NC} Ошибка сборки/запуска контейнеров!"
    echo -e "\n${YELLOW}Вывод Docker Compose:${NC}"
    cat /tmp/docker_compose_output.log
    
    echo -e "\n${YELLOW}Попытка получить логи контейнеров...${NC}"
    docker compose logs 2>&1 || echo "Логи недоступны"
    
    echo -e "\n${YELLOW}Статус контейнеров:${NC}"
    docker compose ps -a 2>&1 || echo "Не удалось получить статус"
    
    exit 1
fi

# Ожидание запуска
echo -e "\n${YELLOW}Ожидание запуска бота...${NC}"
sleep 10

# Проверка статуса с подробной диагностикой
echo -e "${YELLOW}Проверка статуса контейнеров...${NC}"
CONTAINER_STATUS=$(docker compose ps 2>&1)
echo "$CONTAINER_STATUS"

if echo "$CONTAINER_STATUS" | grep -q "Up\|running"; then
    echo -e "${GREEN}✓${NC} Контейнеры успешно запущены"
else
    echo -e "${RED}✗${NC} Ошибка: контейнеры не запущены"
    
    echo -e "\n${YELLOW}Логи redis-bot:${NC}"
    docker logs redis-bot 2>&1 || echo "Контейнер redis-bot не найден"
    
    echo -e "\n${YELLOW}Логи bot:${NC}"
    docker logs bot 2>&1 || echo "Контейнер bot не найден"
    
    echo -e "\n${YELLOW}Docker Compose логи:${NC}"
    docker compose logs 2>&1 || echo "Логи недоступны"
    
    exit 1
fi

# Установка прав на директории
echo -e "\n${YELLOW}Финальная настройка прав доступа...${NC}"
sudo chown -R 1000:1000 /opt/reinar_panel/bot/
find /opt/reinar_panel/bot/ -type d -exec sudo chmod 755 {} +
find /opt/reinar_panel/bot/ -type f -exec sudo chmod 644 {} +
sudo chmod -R 777 /opt/reinar_panel/bot/bot_logs
echo -e "${GREEN}✓${NC} Права установлены"

# Финальное сообщение
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Установка завершена успешно!${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "Директория установки: ${GREEN}${INSTALL_DIR}${NC}"
echo -e "Telegram Bot запущен и готов к работе!\n"

echo -e "${YELLOW}Управление ботом:${NC}"
echo -e "  Перейти в директорию: ${BLUE}cd $INSTALL_DIR${NC}"
echo -e "  Статус:      ${BLUE}docker compose ps${NC}"
echo -e "  Остановка:   ${BLUE}docker compose down${NC}"
echo -e "  Запуск:      ${BLUE}docker compose up -d${NC}"
echo -e "  Перезапуск:  ${BLUE}docker compose restart${NC}"
echo -e "  Логи:        ${BLUE}docker compose logs -f${NC}\n"

echo -e "${YELLOW}Конфигурация:${NC}"
echo -e "  Docker Compose: ${BLUE}$ENV_FILE${NC}"
echo -e "  Бот:            ${BLUE}$ENV_BOT_FILE${NC}\n"

echo -e "${YELLOW}Важная информация:${NC}"
echo -e "  BOT_TOKEN:        ${GREEN}${BOT_TOKEN:0:20}...${NC}"
echo -e "  ADMIN_TG_ID:      ${GREEN}${ADMIN_TG_ID}${NC}"
echo -e "  SUB_SERVICE_URL:  ${GREEN}${SUB_SERVICE_URL}${NC}"

echo -e "${YELLOW}Тестирование бота:${NC}"
echo -e "  1. Откройте Telegram и найдите вашего бота"
echo -e "  2. Отправьте команду /start"
echo -e "  3. Проверьте что бот отвечает\n"

