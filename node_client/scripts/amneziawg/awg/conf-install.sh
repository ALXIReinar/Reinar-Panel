#!/bin/bash

TMP_ID=$1
IP_ADDR=$2       # Например: 172.0.0.1/8 (IPv4) или fd00:1::1/64 (IPv6)
IP_VERSION=$3    # 4 или 6
PANEL_CALLBACK_URL="http://10.0.0.1/api/node/callback"

if [ -z "$TMP_ID" ] || [ -z "$IP_ADDR" ] || [ -z "$IP_VERSION" ]; then
    echo "Ошибка: Необходимы параметры TMP_ID, IP_ADDR, IP_VERSION!"
    exit 1
fi

CONFIG_DIR="/etc/amnezia/amneziawg"
mkdir -p "$CONFIG_DIR"

# --- 1. ПОИСК ПОРТОВ И ИНТЕРФЕЙСОВ ---
find_free_port_range() {
    local range_size=100
    local start_port=20000
    local max_port=60000
    while [ $start_port -le $max_port ]; do
        local end_port=$((start_port + range_size - 1))
        local busy=0
        for p in $(seq $start_port $end_port); do
            if ss -lntu | awk '{print $4}' | grep -q ":$p$"; then
                busy=1
                break
            fi
        done
        if [ $busy -eq 0 ]; then
            echo "$start_port $end_port"
            return 0
        fi
        start_port=$((start_port + range_size))
    done
    echo "20000 20099"
}

find_free_port() {
    local port=$1
    while ss -lntu | awk '{print $4}' | grep -q ":$port$"; do
        port=$((port + 1))
    done
    echo "$port"
}

# Ищем свободный интерфейс awgX
IDX=0
while [ -f "$CONFIG_DIR/awg${IDX}.conf" ] || ip link show "awg${IDX}" >/dev/null 2>&1; do
  IDX=$((IDX+1))
done
IFACE="awg${IDX}"
CONFIG_PATH="$CONFIG_DIR/${IFACE}.conf"

WG_PORT=$(find_free_port 51820)
read -r RANGE_START RANGE_END <<< "$(find_free_port_range)"

# Определяем главный сетевой интерфейс с выходом в интернет (вместо жесткого eth0)
MAIN_IFACE=$(ip route show default | awk '/default/ {print $5}')

# --- 2. ГЕНЕРАЦИЯ КЛЮЧЕЙ И ПАРАМЕТРОВ ---
PRIVATE_KEY=$(awg genkey)
PUBLIC_KEY=$(echo "$PRIVATE_KEY" | awg pubkey)
NODE_HASH_SALT=$(openssl rand -base64 12)

JC=$(( RANDOM % 10 + 3 ))
JMIN=$(( RANDOM % 20 + 40 ))
JMAX=$(( RANDOM % 300 + 700 ))
S1=$(( RANDOM % 100 + 15 ))
S2=$(( RANDOM % 100 + 15 ))
generate_magic() { echo $(( (RANDOM << 15) | RANDOM )); }
H1=$(generate_magic)
H2=$(generate_magic)
H3=$(generate_magic)
H4=$(generate_magic)

# --- 3. НАСТРОЙКА МАРШРУТИЗАЦИИ (Только одна версия IP) ---
if [ "$IP_VERSION" -eq 4 ]; then
    POST_UP="iptables -A FORWARD -i $IFACE -j ACCEPT; iptables -t nat -A POSTROUTING -o $MAIN_IFACE -j MASQUERADE; iptables -t nat -A PREROUTING -p udp --dport $RANGE_START:$RANGE_END -j REDIRECT --to-ports $WG_PORT"
    POST_DOWN="iptables -D FORWARD -i $IFACE -j ACCEPT; iptables -t nat -D POSTROUTING -o $MAIN_IFACE -j MASQUERADE; iptables -t nat -D PREROUTING -p udp --dport $RANGE_START:$RANGE_END -j REDIRECT --to-ports $WG_PORT"
elif [ "$IP_VERSION" -eq 6 ]; then
    POST_UP="ip6tables -A FORWARD -i $IFACE -j ACCEPT; ip6tables -t nat -A POSTROUTING -o $MAIN_IFACE -j MASQUERADE; ip6tables -t nat -A PREROUTING -p udp --dport $RANGE_START:$RANGE_END -j REDIRECT --to-ports $WG_PORT"
    POST_DOWN="ip6tables -D FORWARD -i $IFACE -j ACCEPT; ip6tables -t nat -D POSTROUTING -o $MAIN_IFACE -j MASQUERADE; ip6tables -t nat -D PREROUTING -p udp --dport $RANGE_START:$RANGE_END -j REDIRECT --to-ports $WG_PORT"
else
    echo "Ошибка: Неизвестная версия IP. Используйте 4 или 6."
    exit 1
fi

# --- 4. СОЗДАНИЕ AWG.CONF ---
cat <<EOF > "$CONFIG_PATH"
[Interface]
PrivateKey = $PRIVATE_KEY
Address = $IP_ADDR
ListenPort = $WG_PORT
Jc = $JC
Jmin = $JMIN
Jmax = $JMAX
S1 = $S1
S2 = $S2
H1 = $H1
H2 = $H2
H3 = $H3
H4 = $H4
PostUp = $POST_UP
PostDown = $POST_DOWN
EOF

# --- 5. ЗАПУСК ИНТЕРФЕЙСА ---
# wg-quick использует системный systemd-генератор для управления сервисами
systemctl daemon-reload
systemctl enable --now "awg-quick@${IFACE}"

# --- 6. ОТПРАВКА CALLBACK ---
curl -s -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "tmp_id": "'"$TMP_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "proto_port": '"$WG_PORT"',
           "status": "installed",
           "metrics_port": '$IDX',
           "reload_core_command": "awg syncconf '$IFACE' <(awg-quick strip '$CONFIG_PATH')",
           "node_type": "awg_l3",
           "constant_node_data_obj": {
               "node_ipv'"$IP_VERSION"'_subnet": "'"$IP_ADDR"'",
               "node_public_key": "'"$PUBLIC_KEY"'",
               "node_hop_start": '"$RANGE_START"',
               "node_hop_end": '"$RANGE_END"',
               "node_hash_salt": "'"$NODE_HASH_SALT"'"
           }
         }'

echo "=================================================="
echo "AmneziaWG развернут на интерфейсе $IFACE"
echo "Порт WG: $WG_PORT | Public Key: $PUBLIC_KEY"
echo "=================================================="