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
INSTALL_DIR="$INSTALL_BASE/bot"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Telegram Bot - Удаление${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Проверка прав root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Скрипт должен быть запущен с правами root${NC}"
   echo "Используйте: sudo bash uninstall.sh"
   exit 1
fi

echo -e "${GREEN}✓${NC} Права root подтверждены"

# Проверка существования установки
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Telegram Bot не установлен в ${INSTALL_DIR}${NC}"
    exit 0
fi

# Подтверждение удаления
echo -e "\n${YELLOW}Внимание!${NC} Это действие остановит и удалит:"
echo -e "  - Контейнер Telegram Bot"
echo -e "  - Все файлы в ${INSTALL_DIR}"
echo -e "  - Конфигурационные файлы (.env, .env.bot.prod)"
echo -e "  - Логи бота\n"

if [ -z "$CONFIRM_UNINSTALL" ]; then
    read -p "Вы уверены? (yes/no): " -r
    echo
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo -e "${YELLOW}Удаление отменено${NC}"
        exit 0
    fi
else
    echo -e "${GREEN}✓${NC} Подтверждение получено через переменную окружения CONFIRM_UNINSTALL"
fi

# Остановка и удаление контейнеров
echo -e "\n${YELLOW}Остановка контейнеров...${NC}"
cd "$INSTALL_DIR"
docker compose down -v 2>/dev/null || true
echo -e "${GREEN}✓${NC} Контейнеры остановлены и удалены"

# Удаление директории
echo -e "\n${YELLOW}Удаление файлов...${NC}"
rm -rf "$INSTALL_DIR"
echo -e "${GREEN}✓${NC} Файлы удалены"

# Проверка пустоты базовой директории
if [ -d "$INSTALL_BASE" ] && [ -z "$(ls -A $INSTALL_BASE)" ]; then
    rmdir "$INSTALL_BASE"
    echo -e "${GREEN}✓${NC} Пустая директория $INSTALL_BASE удалена"
fi

# Финальное сообщение
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  Удаление завершено успешно!${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "Telegram Bot полностью удалён из системы\n"

