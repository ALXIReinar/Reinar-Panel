#!/bin/bash

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Константы
INSTALL_DIR="/opt/vpn-panel/web"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  VPN Admin Panel - Деинсталляция${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Проверка прав root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Скрипт должен быть запущен с правами root${NC}"
   echo "Используйте: sudo bash uninstall.sh"
   exit 1
fi

# Проверка существования директории
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Директория $INSTALL_DIR не найдена. Возможно, сервис не установлен.${NC}"
    exit 0
fi

# Подтверждение
echo -e "${YELLOW}ВНИМАНИЕ: Это удалит все контейнеры, volumes и данные!${NC}"
echo -e "Директория: ${BLUE}$INSTALL_DIR${NC}"
read -p "Вы уверены? (yes/NO): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo -e "${YELLOW}Деинсталляция отменена${NC}"
    exit 0
fi

# Остановка и удаление контейнеров
echo -e "\n${YELLOW}Остановка контейнеров...${NC}"
cd "$INSTALL_DIR"
docker compose -f docker-compose.server.yml down -v 2>/dev/null || true
echo -e "${GREEN}✓${NC} Контейнеры остановлены и удалены"

# Удаление образов
echo -e "\n${YELLOW}Удаление Docker образов...${NC}"
docker rmi $(docker images | grep 'reinar_panel' | awk '{print $3}') 2>/dev/null || true
echo -e "${GREEN}✓${NC} Образы удалены"

# Удаление директории установки
read -p "$YELLOW Не удаляйте, если запущена нода или балансировщик$NC | Удалить директорию установки $INSTALL_DIR ? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "$INSTALL_DIR"
    echo -e "${GREEN}✓${NC} Директория удалена"
    
    # Проверить, пуста ли родительская директория
    if [ -d "/opt/vpn-panel" ] && [ -z "$(ls -A /opt/vpn-panel)" ]; then
        rmdir /opt/vpn-panel
        echo -e "${GREEN}✓${NC} Родительская директория /opt/vpn-panel удалена"
    fi
fi

echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Деинсталляция завершена${NC}"
echo -e "${BLUE}========================================${NC}\n"
