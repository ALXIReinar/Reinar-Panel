#!/bin/bash

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SERVICE_NAME="vpn-node-client"
INSTALL_DIR="/opt/vpn-node-client"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  VPN Node Client - Деинсталляция${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Проверка прав root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Скрипт должен быть запущен с правами root${NC}"
   echo "Используйте: sudo bash uninstall.sh"
   exit 1
fi

# Подтверждение
read -p "Вы уверены что хотите удалить VPN Node Client? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Деинсталляция отменена${NC}"
    exit 0
fi

# Остановка сервиса
if systemctl is-active --quiet $SERVICE_NAME; then
    echo -e "\n${YELLOW}Остановка сервиса...${NC}"
    systemctl stop $SERVICE_NAME
    echo -e "${GREEN}✓${NC} Сервис остановлен"
fi

# Отключение автозапуска
if systemctl is-enabled --quiet $SERVICE_NAME 2>/dev/null; then
    echo -e "\n${YELLOW}Отключение автозапуска...${NC}"
    systemctl disable $SERVICE_NAME
    echo -e "${GREEN}✓${NC} Автозапуск отключен"
fi

# Удаление systemd unit
if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ]; then
    echo -e "\n${YELLOW}Удаление systemd unit...${NC}"
    rm /etc/systemd/system/$SERVICE_NAME.service
    systemctl daemon-reload
    echo -e "${GREEN}✓${NC} Systemd unit удален"
fi

# Удаление директории установки
if [ -d "$INSTALL_DIR" ]; then
    echo -e "\n${YELLOW}Удаление директории $INSTALL_DIR...${NC}"
    rm -rf $INSTALL_DIR
    echo -e "${GREEN}✓${NC} Директория удалена"
fi

echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Деинсталляция завершена${NC}"
echo -e "${BLUE}========================================${NC}\n"
