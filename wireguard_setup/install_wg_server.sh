#!/bin/bash

# Скрипт установки WireGuard СЕРВЕРА (главный сервер с админкой)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  WireGuard Server Setup${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Проверка прав root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Ошибка: Скрипт должен быть запущен с правами root${NC}"
   exit 1
fi

# Параметры
WG_DIR="/etc/wireguard"
WG_INTERFACE="wg0"
WG_PORT=51820
PRIVATE_NETWORK="10.0.0.0/24"
SERVER_PRIVATE_IP="10.0.0.1"

echo -e "${YELLOW}Установка WireGuard...${NC}"
apt-get update
apt-get install -y wireguard wireguard-tools

echo -e "${GREEN}✓${NC} WireGuard установлен\n"

# Генерация ключей сервера
echo -e "${YELLOW}Генерация ключей сервера...${NC}"
cd $WG_DIR
umask 077
wg genkey | tee server_private.key | wg pubkey > server_public.key

SERVER_PRIVATE_KEY=$(cat server_private.key)
SERVER_PUBLIC_KEY=$(cat server_public.key)

echo -e "${GREEN}✓${NC} Ключи сгенерированы"
echo -e "  Публичный ключ сервера: ${BLUE}$SERVER_PUBLIC_KEY${NC}\n"

# Получение публичного IP сервера
echo -e "${YELLOW}Определение публичного IP...${NC}"
PUBLIC_IP=$(curl -s ifconfig.me)
echo -e "${GREEN}✓${NC} Публичный IP: ${BLUE}$PUBLIC_IP${NC}\n"

# Создание конфига сервера
echo -e "${YELLOW}Создание конфигурации сервера...${NC}"
cat > $WG_DIR/$WG_INTERFACE.conf << EOF
[Interface]
Address = $SERVER_PRIVATE_IP/24
ListenPort = $WG_PORT
PrivateKey = $SERVER_PRIVATE_KEY

# Включение IP forwarding
PostUp = sysctl -w net.ipv4.ip_forward=1
PostDown = sysctl -w net.ipv4.ip_forward=0

# Клиенты будут добавлены ниже
# Используйте: wg set wg0 peer <PUBLIC_KEY> allowed-ips <CLIENT_IP>/32
EOF

echo -e "${GREEN}✓${NC} Конфигурация создана: $WG_DIR/$WG_INTERFACE.conf\n"

# Включение IP forwarding
echo -e "${YELLOW}Настройка IP forwarding...${NC}"
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p
echo -e "${GREEN}✓${NC} IP forwarding включен\n"

# Настройка firewall
echo -e "${YELLOW}Настройка firewall...${NC}"
if command -v ufw &> /dev/null; then
    ufw allow $WG_PORT/udp
    echo -e "${GREEN}✓${NC} UFW: разрешён порт $WG_PORT/udp"
fi

# Запуск WireGuard
echo -e "\n${YELLOW}Запуск WireGuard...${NC}"
systemctl enable wg-quick@$WG_INTERFACE
systemctl start wg-quick@$WG_INTERFACE

if systemctl is-active --quiet wg-quick@$WG_INTERFACE; then
    echo -e "${GREEN}✓${NC} WireGuard запущен\n"
else
    echo -e "${RED}✗${NC} Ошибка запуска WireGuard"
    exit 1
fi

# Сохранение информации для клиентов
cat > $WG_DIR/server_info.txt << EOF
===========================================
WireGuard Server Information
===========================================

Server Public IP: $PUBLIC_IP
Server WireGuard Port: $WG_PORT
Server Public Key: $SERVER_PUBLIC_KEY
Server Private IP: $SERVER_PRIVATE_IP

Private Network: $PRIVATE_NETWORK

===========================================
Для подключения клиента используйте эту информацию
===========================================
EOF

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  Установка завершена!${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "${YELLOW}Информация о сервере:${NC}"
echo -e "  Публичный IP: ${BLUE}$PUBLIC_IP${NC}"
echo -e "  WireGuard порт: ${BLUE}$WG_PORT${NC}"
echo -e "  Публичный ключ: ${BLUE}$SERVER_PUBLIC_KEY${NC}"
echo -e "  Приватный IP: ${BLUE}$SERVER_PRIVATE_IP${NC}\n"

echo -e "${YELLOW}Сохранено в:${NC} ${BLUE}$WG_DIR/server_info.txt${NC}\n"

echo -e "${YELLOW}Следующие шаги:${NC}"
echo -e "1. Скопируйте публичный ключ сервера"
echo -e "2. Запустите ${BLUE}install_wg_client.sh${NC} на клиентском сервере"
echo -e "3. Добавьте клиента на сервер командой:"
echo -e "   ${BLUE}bash add_wg_client.sh <CLIENT_PUBLIC_KEY> <CLIENT_IP>${NC}\n"

echo -e "${YELLOW}Проверка статуса:${NC}"
echo -e "  ${BLUE}wg show${NC}\n"
