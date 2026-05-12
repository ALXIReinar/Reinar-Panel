#!/bin/bash

# Скрипт для добавления клиента на WireGuard сервер

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Скрипт должен быть запущен с правами root${NC}"
   exit 1
fi

WG_INTERFACE="wg0"

# Проверка аргументов
if [ $# -lt 2 ]; then
    echo -e "${RED}Использование: $0 <CLIENT_PUBLIC_KEY> <CLIENT_PRIVATE_IP>${NC}"
    echo -e "Пример: $0 'abc123...' '10.0.0.2'"
    exit 1
fi

CLIENT_PUBLIC_KEY=$1
CLIENT_PRIVATE_IP=$2

echo -e "${YELLOW}Добавление клиента в WireGuard...${NC}"
echo -e "  Публичный ключ: ${BLUE}$CLIENT_PUBLIC_KEY${NC}"
echo -e "  Приватный IP: ${BLUE}$CLIENT_PRIVATE_IP${NC}\n"

# Добавление peer
wg set $WG_INTERFACE peer "$CLIENT_PUBLIC_KEY" allowed-ips "$CLIENT_PRIVATE_IP/32"

# Сохранение конфигурации
wg-quick save $WG_INTERFACE

echo -e "${GREEN}✓${NC} Клиент добавлен!\n"

echo -e "${YELLOW}Текущие подключения:${NC}"
wg show

echo -e "\n${YELLOW}Проверка подключения:${NC}"
echo -e "  ${BLUE}ping $CLIENT_PRIVATE_IP${NC}\n"
