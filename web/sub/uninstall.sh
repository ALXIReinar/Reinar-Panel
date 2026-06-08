#!/bin/bash

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Константы
INSTALL_BASE="/opt/vpn-panel"
INSTALL_DIR="$INSTALL_BASE/web"
SUB_DIR="$INSTALL_DIR/sub"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  VPN Sub Service - Деинсталляция${NC}"
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
echo -e "${YELLOW}ВНИМАНИЕ: Это остановит и удалит Sub Service контейнеры!${NC}"
echo -e "Директория: ${BLUE}$INSTALL_DIR${NC}"
read -p "Вы уверены? (yes/NO): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo -e "${YELLOW}Деинсталляция отменена${NC}"
    exit 0
fi

# Остановка и удаление sub контейнеров
echo -e "\n${YELLOW}Остановка Sub Service контейнеров...${NC}"
cd "$INSTALL_DIR"
docker compose stop sub-service arq-sub-worker 2>/dev/null || true
docker compose rm -f sub-service arq-sub-worker 2>/dev/null || true
echo -e "${GREEN}✓${NC} Контейнеры остановлены и удалены"

# Удаление образов sub сервиса
echo -e "\n${YELLOW}Удаление Docker образов...${NC}"
docker images | grep -E 'web-(sub-service|arq-sub-worker)' | awk '{print $3}' | xargs -r docker rmi 2>/dev/null || true
echo -e "${GREEN}✓${NC} Образы удалены"

# Комментирование строки в docker-compose.yml
echo -e "\n${YELLOW}Обновление docker-compose.yml...${NC}"
COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"

if [ -f "$COMPOSE_FILE" ]; then
    # Комментируем строчку с sub/docker-compose.yml
    sed -i 's/^  - sub\/docker-compose\.yml$/  # - sub\/docker-compose.yml/' "$COMPOSE_FILE"
    echo -e "${GREEN}✓${NC} docker-compose.yml обновлён"
fi

# Удаление .env.sub.prod
read -p "Удалить конфигурацию Sub Service ($SUB_DIR/.env.sub.prod)? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -f "$SUB_DIR/.env.sub.prod"
    echo -e "${GREEN}✓${NC} Конфигурация удалена"
fi

# Удаление логов
read -p "Удалить логи Sub Service? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "$INSTALL_DIR/.sub/sub_logs" 2>/dev/null || true
    rm -rf "$INSTALL_DIR/.sub/arq_logs" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Логи удалены"
fi

echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Деинсталляция завершена${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "${YELLOW}Примечание:${NC}"
echo -e "  Web Admin Panel остался установленным"
echo -e "  Для полного удаления используйте: ${BLUE}cd $INSTALL_DIR && bash uninstall.sh${NC}\n"
