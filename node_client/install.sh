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
INSTALL_DIR="$INSTALL_BASE/node"
SERVICE_NAME="vpn-node-client"
PYTHON_MIN_VERSION="3.10"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  VPN Node Client - Установка${NC}"
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

# Проверка наличия необходимых файлов
echo -e "\n${YELLOW}Проверка исходных файлов...${NC}"
REQUIRED_FILES=("requirements.txt" "main.py" "config.py")
REQUIRED_DIRS=("api" "schemas")

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$SCRIPT_DIR/$file" ]; then
        echo -e "${RED}✗${NC} Файл не найден: $file"
        echo "Убедитесь, что скрипт запущен из директории node_client/"
        exit 1
    fi
done

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ ! -d "$SCRIPT_DIR/$dir" ]; then
        echo -e "${RED}✗${NC} Директория не найдена: $dir"
        echo "Убедитесь, что скрипт запущен из директории node_client/"
        exit 1
    fi
done

echo -e "${GREEN}✓${NC} Все необходимые файлы найдены"

echo -e "\nОбновление системы"
apt-get update -y && apt-get upgrade -y

echo -e "\nНастройка имени Ноды"
read -p "Введите имя ноды(будет отображаться в админ панели): " NODE_NAME

# Интерактивный выбор порта
echo -e "\n${YELLOW}Настройка порта для Node Client${NC}"
DEFAULT_PORT=8100

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

# Запрос приватного IP админки
echo -e "\n${YELLOW}Настройка приватной сети${NC}"
DEFAULT_ADMIN_IP="10.0.0.1"

read -p "Введите приватный IP админ-панели (по умолчанию $DEFAULT_ADMIN_IP): " ADMIN_PRIVATE_IP
ADMIN_PRIVATE_IP=${ADMIN_PRIVATE_IP:-$DEFAULT_ADMIN_IP}

echo -e "${GREEN}✓${NC} Приватный IP админки: $ADMIN_PRIVATE_IP"

# Проверка наличия Python
echo -e "\n${YELLOW}Проверка Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗${NC} Python 3 не найден"
    echo "Установите Python 3.10+ и повторите установку"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo -e "${GREEN}✓${NC} Python ${PYTHON_VERSION} найден"

# Проверка версии Python
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo -e "${RED}✗${NC} Требуется Python 3.10 или выше (найден ${PYTHON_VERSION})"
    exit 1
fi

# Проверка pip
echo -e "\n${YELLOW}Проверка pip...${NC}"
if ! command -v pip3 &> /dev/null; then
    echo -e "${YELLOW}pip3 не найден, устанавливаем...${NC}"
    apt-get update && apt-get install -y python3-pip python3-venv
fi
echo -e "${GREEN}✓${NC} pip3 доступен"

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
cp -r $SCRIPT_DIR/api $INSTALL_DIR/node_client/
cp -r $SCRIPT_DIR/schemas $INSTALL_DIR/node_client/
cp $SCRIPT_DIR/*.py $INSTALL_DIR/node_client/ 2>/dev/null || true

# Копируем файлы конфигурации и зависимости в корень
cp $SCRIPT_DIR/requirements.txt $INSTALL_DIR/
cp $SCRIPT_DIR/.env.example $INSTALL_DIR/ 2>/dev/null || true
cp $SCRIPT_DIR/README.md $INSTALL_DIR/ 2>/dev/null || true

# Копируем uninstall.sh в директорию установки
cp $SCRIPT_DIR/uninstall.sh $INSTALL_DIR/ 2>/dev/null || true

echo -e "${GREEN}✓${NC} Файлы скопированы"

# Создание виртуального окружения
echo -e "\n${YELLOW}Создание виртуального окружения...${NC}"
cd $INSTALL_DIR
python3 -m venv venv
echo -e "${GREEN}✓${NC} Виртуальное окружение создано"

# Права для использования
sudo chown -R 1000:1000 /opt/vpn-panel/node

# Для всех папок ставим стандартные 755 (читать и заходить могут все, писать - только владелец)
find /opt/vpn-panel/ -type d -exec sudo chmod 755 {} +

# Для всех файлов ставим стандартные 644 (читать могут все, писать - только владелец)
find /opt/vpn-panel/ -type f -exec sudo chmod 644 {} +

# Разрешаем запускать весь bin
chmod 755 -R $INSTALL_DIR/venv/bin

# Активация venv и установка зависимостей
echo -e "\n${YELLOW}Установка зависимостей...${NC}"
$INSTALL_DIR/venv/bin/pip install --upgrade pip
$INSTALL_DIR/venv/bin/pip install -r requirements.txt
echo -e "${GREEN}✓${NC} Зависимости установлены"

# Создание .env файла если его нет
if [ ! -f "$INSTALL_DIR/.env.node.prod" ]; then
    echo -e "\n${YELLOW}Создание конфигурационного файла...${NC}"
    cat > "$INSTALL_DIR/.env.node.prod" <<ENVEOF
# Node Client Configuration
NODE_PORT=${NODE_PORT}
NODE_NAME=${NODE_NAME}
COMMAND_TIMEOUT=30

# Write Buffer Settings (батчинг записи конфигов)
WRITE_BUFFER_INTERVAL=10
WRITE_BUFFER_SIZE=5

# Приватный IP админ-панели
ADMIN_PANEL_PRIVATE_IP=${ADMIN_PRIVATE_IP}
ENVEOF
    echo -e "${GREEN}✓${NC} Конфигурация создана: $INSTALL_DIR/.env.node.prod"
else
    echo -e "\n${YELLOW}Обновление конфигурационного файла...${NC}"
    # Обновляем порт в существующем файле
    sed -i "s/^NODE_PORT=.*/NODE_PORT=$NODE_PORT/" $INSTALL_DIR/.env.node.prod
    
    # Обновляем имя ноды
    sed -i "s/^NODE_NAME=.*/NODE_NAME=$NODE_NAME/" $INSTALL_DIR/.env.node.prod
    
    # Добавляем ADMIN_PANEL_PRIVATE_IP если его нет
    if ! grep -q "ADMIN_PANEL_PRIVATE_IP" $INSTALL_DIR/.env.node.prod; then
        echo "" >> $INSTALL_DIR/.env.node.prod
        echo "# Приватный IP админ-панели" >> $INSTALL_DIR/.env.node.prod
        echo "ADMIN_PANEL_PRIVATE_IP=$ADMIN_PRIVATE_IP" >> $INSTALL_DIR/.env.node.prod
    else
        sed -i "s/^ADMIN_PANEL_PRIVATE_IP=.*/ADMIN_PANEL_PRIVATE_IP=$ADMIN_PRIVATE_IP/" $INSTALL_DIR/.env.node.prod
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
Description=VPN Node Client API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=$INSTALL_DIR"
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
sleep 2

# Проверка статуса
if systemctl is-active --quiet $SERVICE_NAME; then
    echo -e "${GREEN}✓${NC} Сервис успешно запущен"
else
    echo -e "${RED}✗${NC} Ошибка запуска сервиса"
    echo "Проверьте логи: journalctl -u $SERVICE_NAME -n 50"
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
echo -e "  Скрипт: ${BLUE}bash $INSTALL_DIR/uninstall.sh${NC}\n"
