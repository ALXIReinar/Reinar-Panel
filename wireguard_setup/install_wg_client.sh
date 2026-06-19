#!/bin/bash

# Скрипт установки WireGuard КЛИЕНТА (нода)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  WireGuard Client Setup${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Проверка прав root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Скрипт должен быть запущен с правами root${NC}"
   exit 1
fi

# Параметры
WG_DIR="/etc/wireguard"
WG_INTERFACE="wg0"

echo -e "${YELLOW}Установка WireGuard...${NC}"
apt-get update
apt-get install -y wireguard wireguard-tools

echo -e "${GREEN}✓${NC} WireGuard установлен\n"

# Генерация ключей клиента
echo -e "${YELLOW}Генерация ключей клиента...${NC}"
cd $WG_DIR
umask 077
wg genkey | tee client_private.key | wg pubkey > client_public.key

CLIENT_PRIVATE_KEY=$(cat client_private.key)
CLIENT_PUBLIC_KEY=$(cat client_public.key)

echo -e "${GREEN}✓${NC} Ключи сгенерированы"
echo -e "  Публичный ключ клиента: ${BLUE}$CLIENT_PUBLIC_KEY${NC}\n"

# Запрос информации о сервере
echo -e "${YELLOW}Введите информацию о WireGuard сервере:${NC}\n"

read -p "Публичный IP сервера: " SERVER_PUBLIC_IP
read -p "WireGuard порт сервера (по умолчанию 51820): " SERVER_PORT
SERVER_PORT=${SERVER_PORT:-51820}
read -p "Публичный ключ сервера: " SERVER_PUBLIC_KEY
read -p "Приватный IP сервера (по умолчанию 10.0.0.1): " SERVER_PRIVATE_IP
SERVER_PRIVATE_IP=${SERVER_PRIVATE_IP:-10.0.0.1}
read -p "Приватный IP этого клиента (например 10.0.0.2): " CLIENT_PRIVATE_IP

echo -e "\n${YELLOW}Создание конфигурации клиента...${NC}"

# Создание конфига клиента
cat > $WG_DIR/$WG_INTERFACE.conf << EOF
[Interface]
Address = $CLIENT_PRIVATE_IP/24
PrivateKey = $CLIENT_PRIVATE_KEY

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $SERVER_PUBLIC_IP:$SERVER_PORT
AllowedIPs = 10.0.0.0/24
PersistentKeepalive = 25
EOF

echo -e "${GREEN}✓${NC} Конфигурация создана: $WG_DIR/$WG_INTERFACE.conf\n"

# Запуск WireGuard
echo -e "${YELLOW}Запуск WireGuard...${NC}"
systemctl enable wg-quick@$WG_INTERFACE
systemctl start wg-quick@$WG_INTERFACE

if systemctl is-active --quiet wg-quick@$WG_INTERFACE; then
    echo -e "${GREEN}✓${NC} WireGuard запущен\n"
else
    echo -e "${RED}✗${NC} Ошибка запуска WireGuard"
    exit 1
fi

# Сохранение информации
cat > $WG_DIR/client_info.txt << EOF
===========================================
WireGuard Client Information
===========================================

Client Public Key: $CLIENT_PUBLIC_KEY
Client Private IP: $CLIENT_PRIVATE_IP

Server Public IP: $SERVER_PUBLIC_IP
Server WireGuard Port: $SERVER_PORT
Server Private IP: $SERVER_PRIVATE_IP

===========================================
EOF

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  Установка завершена!${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "${YELLOW}Информация о клиенте:${NC}"
echo -e "  Публичный ключ: ${BLUE}$CLIENT_PUBLIC_KEY${NC}"
echo -e "  Приватный IP: ${BLUE}$CLIENT_PRIVATE_IP${NC}\n"

echo -e "${YELLOW}Сохранено в:${NC} ${BLUE}$WG_DIR/client_info.txt${NC}\n"

echo -e "${RED}ВАЖНО!${NC} Теперь на ${YELLOW}СЕРВЕРЕ${NC} выполните:"
echo -e "${BLUE}bash add_wg_client.sh $CLIENT_PUBLIC_KEY $CLIENT_PRIVATE_IP${NC}\n"

echo -e "${YELLOW}Проверка подключения:${NC}"
echo -e "  ${BLUE}wg show${NC}"
echo -e "  ${BLUE}ping $SERVER_PRIVATE_IP${NC}\n"
