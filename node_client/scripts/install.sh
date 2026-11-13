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
INSTALL_DIR="$INSTALL_BASE/node"
# Версия Python нод-клиента. Системный python3 не используется: в Ubuntu 22.04 он 3.10,
# поэтому интерпретатор ставит uv — в каталог установки, не трогая систему
PYTHON_VERSION="3.12"
UV_DIR="$INSTALL_DIR/uv"
SERVICE_NAME="reinar-node"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Reinar Node Client - Установка${NC}"
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

NODE_CLIENT_DIR="$(dirname "$SCRIPT_DIR")"


# Проверка наличия необходимых файлов
echo -e "\n${YELLOW}Проверка исходных файлов...${NC}"
REQUIRED_FILES=("requirements.txt" "main.py" "config.py")
REQUIRED_DIRS=("api" "schemas")

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$NODE_CLIENT_DIR/$file" ]; then
        echo -e "${RED}✗${NC} Файл не найден: $file"
        echo "Убедитесь, что скрипт запущен из директории node_client/"
        exit 1
    fi
done

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ ! -d "$NODE_CLIENT_DIR/$dir" ]; then
        echo -e "${RED}✗${NC} Директория не найдена: $dir"
        echo "Убедитесь, что скрипт запущен из директории node_client/"
        exit 1
    fi
done

echo -e "${GREEN}✓${NC} Все необходимые файлы найдены"

if [ -z "$CI" ]; then
    echo -e "\nОбновление системы"
    apt install uuid-runtime jq unzip curl ca-certificates
    apt-get update -y && apt-get upgrade -y
fi

echo -e "\nНастройка имени Ноды"

# NODE_TITLE должен совпадать с названием физической ноды в админке (nodes.title):
# по нему нод-клиент при старте запрашивает свои виртуальные ноды (/startup).
# NODE_NAME — устаревшее имя переменной, принимаем его для совместимости.
NODE_TITLE=${NODE_TITLE:-$NODE_NAME}
# Те же правила, что у админки (web/schemas/node_schema.py): до 64 символов, без символов, ломающих URL и sed
node_title_problem() {
    if [ -z "$NODE_TITLE" ]; then
        echo "пустое"
    elif [ ${#NODE_TITLE} -gt 64 ]; then
        echo "длиннее 64 символов"
    elif [[ "$NODE_TITLE" == *[\/\\\&\#\?%\'\"]* ]]; then
        echo "содержит недопустимые символы (разрешены буквы, цифры, пробел, _ . -)"
    fi
}
while [ -n "$(node_title_problem)" ]; do
    if [ -n "$NODE_TITLE" ]; then
        echo -e "${RED}✗${NC} Имя ноды $(node_title_problem)"
    fi
    read -p "Введите имя ноды (как физическая нода называется в админ панели, до 64 символов): " NODE_TITLE
done

# Интерактивный выбор порта
echo -e "\n${YELLOW}Настройка порта для Node Client${NC}"
DEFAULT_PORT=8100
if [ -z "$NODE_PORT" ]; then
    while true; do
        read -p "Введите порт для API (по умолчанию $DEFAULT_PORT): " USER_PORT
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

    NODE_PORT=$USER_PORT
fi

if [ -z "$CI" ]; then
  echo -e "${YELLOW} Настройка пересылки пакетов (Необходимо для работы xray, sing-box, e.t.c)"

  echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-custom-forwarding.conf
  echo "net.ipv6.conf.all.forwarding=1" >> /etc/sysctl.d/99-custom-forwarding.conf
fi

sysctl --system > /dev/null

# Запрос приватного IP админки
echo -e "\n${YELLOW}Настройка приватной сети${NC}"
DEFAULT_ADMIN_IP="10.0.0.1"

if [ -z "$ADMIN_PANEL_PRIVATE_IP" ]; then
    read -p "Введите приватный IP админ-панели (по умолчанию $DEFAULT_ADMIN_IP): " ADMIN_PANEL_PRIVATE_IP
fi
ADMIN_PANEL_PRIVATE_IP=${ADMIN_PANEL_PRIVATE_IP:-$DEFAULT_ADMIN_IP}

echo -e "${GREEN}✓${NC} Приватный IP админки: $ADMIN_PANEL_PRIVATE_IP"

# Порт админки: нод-клиент при старте запрашивает у неё свои виртуальные ноды (/startup).
# Значения по умолчанию нет намеренно — ошибочный порт тихо оставил бы ноду без инициализации
while ! [[ "$ADMIN_PANEL_PORT" =~ ^[0-9]+$ ]] || [ "$ADMIN_PANEL_PORT" -lt 1 ] || [ "$ADMIN_PANEL_PORT" -gt 65535 ]; do
    if [ -n "$CI" ]; then
        echo -e "${RED}✗${NC} ADMIN_PANEL_PORT не задан или неверен: '${ADMIN_PANEL_PORT}'"
        exit 1
    fi
    if [ -n "$ADMIN_PANEL_PORT" ]; then
        echo -e "${RED}✗${NC} Порт должен быть числом от 1 до 65535"
    fi
    read -p "Введите порт админ-панели: " ADMIN_PANEL_PORT
done
echo -e "${GREEN}✓${NC} Порт админки: $ADMIN_PANEL_PORT"

# Остановка существующего сервиса если запущен
if systemctl is-active --quiet $SERVICE_NAME; then
    echo -e "\n${YELLOW}Остановка существующего сервиса...${NC}"
    systemctl stop $SERVICE_NAME
    echo -e "${GREEN}✓${NC} Сервис остановлен"
fi

# Создание директории установки
echo -e "\n${YELLOW}Создание директории ${INSTALL_DIR}...${NC}"
mkdir -p $INSTALL_DIR
echo -e "${GREEN}✓${NC} Директория создана"

# Копирование файлов
echo -e "\n${YELLOW}Копирование файлов приложения...${NC}"

# Копируем папку node_client как пакет
mkdir -p $INSTALL_DIR/node_client
cp -r $NODE_CLIENT_DIR/* $INSTALL_DIR/node_client


echo -e "${GREEN}✓${NC} Файлы скопированы"

# uv: ставит Python нужной версии и зависимости. Всё лежит в $UV_DIR — uninstall.sh удаляет его вместе с установкой.
# UV_UNMANAGED_INSTALL — установка в указанный каталог без правки PATH и профилей оболочки
echo -e "\n${YELLOW}Установка uv...${NC}"
if [ ! -x "$UV_DIR/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$UV_DIR" sh
fi
echo -e "${GREEN}✓${NC} $($UV_DIR/uv --version)"

# Python — тоже в каталоге установки, а не в домашнем каталоге того, кто запустил скрипт; кеш пакетов на ноде не нужен
export UV_PYTHON_INSTALL_DIR="$UV_DIR/python"
export UV_NO_CACHE=1

# Создание виртуального окружения. Старое удаляем: оно могло быть собрано на системном Python 3.10
echo -e "\n${YELLOW}Создание виртуального окружения (Python ${PYTHON_VERSION})...${NC}"
cd $INSTALL_DIR
rm -rf $INSTALL_DIR/venv
# --managed-python: только Python от uv, даже если в системе есть подходящий — одинаковая сборка на всех нодах
$UV_DIR/uv venv --managed-python --python $PYTHON_VERSION $INSTALL_DIR/venv
echo -e "${GREEN}✓${NC} Виртуальное окружение создано: $($INSTALL_DIR/venv/bin/python --version)"

# Установка зависимостей
echo -e "\n${YELLOW}Установка зависимостей...${NC}"
$UV_DIR/uv pip install --python $INSTALL_DIR/venv/bin/python -r $INSTALL_DIR/node_client/requirements.txt
echo -e "${GREEN}✓${NC} Зависимости установлены"

# Сервис работает от root — владельцем кода тоже должен быть root, иначе другой пользователь
# мог бы подменить код, который исполняется с правами root
chown -R root:root $INSTALL_DIR

# Создание .env файла если его нет
if [ ! -f "$INSTALL_DIR/.env.node.prod" ]; then
    echo -e "\n${YELLOW}Создание конфигурационного файла...${NC}"
    cat > "$INSTALL_DIR/.env.node.prod" <<ENVEOF
# Node Client Configuration
NODE_PORT=${NODE_PORT}
NODE_TITLE=${NODE_TITLE}
COMMAND_TIMEOUT=30

PYTHONUNBUFFERED=1

# Write Buffer Settings (батчинг записи конфигов)
WRITE_BUFFER_INTERVAL=10
WRITE_BUFFER_SIZE=5

# Приватный IP и порт админ-панели
ADMIN_PANEL_PRIVATE_IP=${ADMIN_PANEL_PRIVATE_IP}
ADMIN_PANEL_PORT=${ADMIN_PANEL_PORT}
ENVEOF
    echo -e "${GREEN}✓${NC} Конфигурация создана: $INSTALL_DIR/.env.node.prod"
else
    echo -e "\n${YELLOW}Обновление конфигурационного файла...${NC}"
    # Обновляем порт в существующем файле
    sed -i "s/^NODE_PORT=.*/NODE_PORT=$NODE_PORT/" $INSTALL_DIR/.env.node.prod
    
    # Обновляем имя ноды. Старое имя переменной NODE_NAME переименовываем в NODE_TITLE
    if grep -q "^NODE_TITLE=" $INSTALL_DIR/.env.node.prod; then
        sed -i "s/^NODE_TITLE=.*/NODE_TITLE=$NODE_TITLE/" $INSTALL_DIR/.env.node.prod
        sed -i "/^NODE_NAME=/d" $INSTALL_DIR/.env.node.prod
    elif grep -q "^NODE_NAME=" $INSTALL_DIR/.env.node.prod; then
        sed -i "s/^NODE_NAME=.*/NODE_TITLE=$NODE_TITLE/" $INSTALL_DIR/.env.node.prod
    else
        echo "NODE_TITLE=$NODE_TITLE" >> $INSTALL_DIR/.env.node.prod
    fi
    
    # Добавляем ADMIN_PANEL_PRIVATE_IP если его нет
    if ! grep -q "ADMIN_PANEL_PRIVATE_IP" $INSTALL_DIR/.env.node.prod; then
        echo "" >> $INSTALL_DIR/.env.node.prod
        echo "# Приватный IP админ-панели" >> $INSTALL_DIR/.env.node.prod
        echo "ADMIN_PANEL_PRIVATE_IP=$ADMIN_PANEL_PRIVATE_IP" >> $INSTALL_DIR/.env.node.prod
    else
        sed -i "s/^ADMIN_PANEL_PRIVATE_IP=.*/ADMIN_PANEL_PRIVATE_IP=$ADMIN_PANEL_PRIVATE_IP/" $INSTALL_DIR/.env.node.prod
    fi

    # Порт админки: без него нод-клиент не стартует
    if grep -q "^ADMIN_PANEL_PORT=" $INSTALL_DIR/.env.node.prod; then
        sed -i "s/^ADMIN_PANEL_PORT=.*/ADMIN_PANEL_PORT=$ADMIN_PANEL_PORT/" $INSTALL_DIR/.env.node.prod
    else
        echo "ADMIN_PANEL_PORT=$ADMIN_PANEL_PORT" >> $INSTALL_DIR/.env.node.prod
    fi
    
    # Добавляем Write Buffer настройки если их нет
    if ! grep -q "WRITE_BUFFER_INTERVAL" $INSTALL_DIR/.env.node.prod; then
        echo "" >> $INSTALL_DIR/.env.node.prod
        echo "# Write Buffer Settings (батчинг записи конфигов)" >> $INSTALL_DIR/.env.node.prod
        echo "WRITE_BUFFER_INTERVAL=10" >> $INSTALL_DIR/.env.node.prod
        echo "WRITE_BUFFER_SIZE=5" >> $INSTALL_DIR/.env.node.prod
    fi
    
    echo -e "${GREEN}✓${NC} Конфигурация обновлена"
fi

# Создание systemd unit
echo -e "\n${YELLOW}Создание systemd service...${NC}"
cat > /etc/systemd/system/$SERVICE_NAME.service << EOF
[Unit]
Description=Reinar Panel Node Client
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=$INSTALL_DIR"
Environment="ENV_FILE=$INSTALL_DIR/.env.node.prod"
ExecStart=$INSTALL_DIR/venv/bin/python -m node_client.main
Restart=always
RestartSec=10

# Логирование
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

[Install]
WantedBy=multi-user.target
EOF
echo -e "${GREEN}✓${NC} Systemd unit создан"

# Перезагрузка systemd
echo -e "\n${YELLOW}Перезагрузка systemd...${NC}"
systemctl daemon-reload
echo -e "${GREEN}✓${NC} Systemd перезагружен"

# Включение автозапуска
echo -e "\n${YELLOW}Включение автозапуска...${NC}"
systemctl enable $SERVICE_NAME
echo -e "${GREEN}✓${NC} Автозапуск включен"

# Запуск сервиса
echo -e "\n${YELLOW}Запуск сервиса...${NC}"
systemctl start $SERVICE_NAME
sleep 3

# Проверка статуса с выводом логов при ошибке
if systemctl is-active --quiet $SERVICE_NAME; then
    echo -e "${GREEN}✓${NC} Сервис успешно запущен"
else
    echo -e "${RED}✗${NC} Ошибка запуска сервиса"
    echo -e "\n${RED}========== Логи сервиса (последние 50 строк) ==========${NC}"
    journalctl -u $SERVICE_NAME -n 50 --no-pager || true
    echo -e "\n${RED}========== Статус сервиса ==========${NC}"
    systemctl status $SERVICE_NAME --no-pager || true
    echo -e "\n${BLUE}========== Конфигурация .env.node.prod ==========${NC}"
    cat $INSTALL_DIR/.env.node.prod || true
    echo -e "\n${BLUE}========== Структура $INSTALL_DIR ==========${NC}"
    ls -la $INSTALL_DIR/ || true
    ls -la $INSTALL_DIR/node_client/ || true
    exit 1
fi

# Финальное сообщение
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Установка завершена успешно!${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "Сервис установлен и запущен на порту: ${GREEN}$NODE_PORT${NC}"
echo -e "API доступен по адресу: ${GREEN}http://localhost:$NODE_PORT${NC}"
echo -e "Swagger документация: ${GREEN}http://localhost:$NODE_PORT/docs${NC}\n"

echo -e "${YELLOW}Управление сервисом:${NC}"
echo -e "  Статус:      ${BLUE}systemctl status $SERVICE_NAME${NC}"
echo -e "  Остановка:   ${BLUE}systemctl stop $SERVICE_NAME${NC}"
echo -e "  Запуск:      ${BLUE}systemctl start $SERVICE_NAME${NC}"
echo -e "  Перезапуск:  ${BLUE}systemctl restart $SERVICE_NAME${NC}"
echo -e "  Логи:        ${BLUE}journalctl -u $SERVICE_NAME -f${NC}\n"

echo -e "${YELLOW}Конфигурация:${NC}"
echo -e "  Файл: ${BLUE}$INSTALL_DIR/.env.node.prod${NC}\n"

echo -e "${YELLOW}Деинсталляция:${NC}"
echo -e "  Скрипт: ${BLUE}bash $INSTALL_DIR/node_client/scripts/uninstall.sh${NC}\n"
