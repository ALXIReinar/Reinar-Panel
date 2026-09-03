#!/bin/bash

PANEL_CALLBACK_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/callback"
PANEL_CONFIRM_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/confirm"

log() { echo -e "$1" >&2; }


if [ -z "$NODE_ID" ] || [ -z "$PROTO_ID" ] || [ -z "$IP_ADDR" ] || [ -z "$IP_VERSION" ]; then
    log "Ошибка: Необходимы переменные NODE_ID, PROTO_ID, IP_ADDR, IP_VERSION!"
    exit 1
fi

if [[ "$IP_VERSION" != "4" && "$IP_VERSION" != "6" ]]; then
    log "IP_VERSION must be 4 or 6"
    exit 1
fi

if [ -z "$TITLE" ]; then
    log "Название для виртуальной ноды не указано. Будет использовано составное"
    TITLE="Vnode_PrId-'$PROTO_ID'_NId-'$NODE_ID'"
fi

CONFIG_DIR="/etc/reinar/configs/amneziawg"
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

log "1. Регистрация ноды в панели и получение node_proto_id..."

REG_RESPONSE=$(mktemp)
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$REG_RESPONSE" -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "proto_id": "'"$PROTO_ID"'",
           "node_id": "'"$NODE_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "proto_port": '"$WG_PORT"',
           "metrics_port": '$IDX',
           "reload_core_command": "awg syncconf '$IFACE' <(awg-quick strip '$CONFIG_PATH')",
           "metrics_command": "awg show '$IFACE' dump",
           "title": "'"$TITLE"'",
           "constant_node_data_obj": {
               "node_ipv'"$IP_VERSION"'_subnet": "'"$IP_ADDR"'",
               "node_public_key": "'"$PUBLIC_KEY"'",
               "node_hop_start": '"$RANGE_START"',
               "node_hop_end": '"$RANGE_END"',
               "node_hash_salt": "'"$NODE_HASH_SALT"'"
           }
         }')

if [ "$HTTP_CODE" -ne 200 ]; then
    log "\033[31mОшибка регистрации (HTTP $HTTP_CODE): $(cat "$REG_RESPONSE")\033[0m"
    rm -f "$REG_RESPONSE"
    exit 1
fi

NODE_PROTO_ID=$(jq -r '.node_proto_id' "$REG_RESPONSE")
TITLE=$(jq -r '.title' "$REG_RESPONSE")
rm -f "$REG_RESPONSE"

log "Назначен NODE_PROTO_ID: $NODE_PROTO_ID"


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
    log "Ошибка: Неизвестная версия IP. Используйте 4 или 6."
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

SERVICE_NAME="awg-quick@${IFACE}"

log "2. Запуск юнита $SERVICE_NAME..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >&2
systemctl restart "$SERVICE_NAME" >&2

sleep 1

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    log "\033[31mСервис $SERVICE_NAME не смог запуститься! Откат...\033[0m"
    systemctl stop "$SERVICE_NAME" || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$CONFIG_PATH" "$SERVICE_PATH"
    systemctl daemon-reload

    # Оповещаем панель о фейле
    curl -s -X POST "$PANEL_CONFIRM_URL" -H "Content-Type: application/json" \
         -d '{"node_proto_id": '"$NODE_PROTO_ID"', "status": 3}' >/dev/null || true
    exit 1
fi

# 6. Финализация статуса в панели
curl -s -X POST "$PANEL_CONFIRM_URL" -H "Content-Type: application/json" \
     -d '{"node_proto_id": '"$NODE_PROTO_ID"', "status": 2}' >/dev/null



log "=================================================="
log "✓ Виртуальная нода успешно создана!"
log "Node Proto ID: $NODE_PROTO_ID"
log "Config Path: $CONFIG_PATH"
log "Title: $TITLE"
log "Интерфейс: $IFACE"
log "Порт WG: $WG_PORT | Public Key: $PUBLIC_KEY"
log "=================================================="

# 7. Возврат результата в stdout (JSON) для вызывающего скрипта
jq -n \
  --arg node_proto_id "$NODE_PROTO_ID" \
  --arg service_name "$SERVICE_NAME" \
  '{node_proto_id: $node_proto_id, service_name: $service_name}'
