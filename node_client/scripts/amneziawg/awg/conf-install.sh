#!/bin/bash
set -euo pipefail
umask 077

PANEL_PROTOCOLS_URL="http://${ADMIN_PANEL_IP:-10.0.0.1}:${ADMIN_PANEL_PORT:?Укажи ADMIN_PANEL_PORT}/api/v1/server/nodes/protocols"
AWG_ROUTING=${AWG_ROUTING:-1}
AWG_AUTOSTART=${AWG_AUTOSTART:-1}

log() { echo -e "$1" >&2; }

if [[ "$EUID" -ne 0 ]]; then
    log "Ошибка: скрипт требует root для создания конфига и запуска systemd."
    exit 1
fi

if [[ -z "${NODE_ID:-}" || -z "${PROTO_ID:-}" || -z "${IP_ADDR:-}" || -z "${IP_VERSION:-}" ]]; then
    log "Ошибка: Необходимы переменные NODE_ID, PROTO_ID, IP_ADDR, IP_VERSION!"
    exit 1
fi

if [[ "$IP_VERSION" != "4" && "$IP_VERSION" != "6" ]]; then
    log "IP_VERSION must be 4 or 6"
    exit 1
fi

if [[ ! "$AWG_ROUTING" =~ ^[01]$ || ! "$AWG_AUTOSTART" =~ ^[01]$ ]]; then
    log "AWG_ROUTING и AWG_AUTOSTART должны быть 0 или 1."
    exit 1
fi

python3 - "$IP_ADDR" "$IP_VERSION" <<'PY'
import ipaddress
import sys

address, version = sys.argv[1:]
try:
    interface = ipaddress.ip_interface(address)
    if "/" not in address or "%" in address or interface.version != int(version):
        raise ValueError("нужен адрес интерфейса с CIDR нужной версии")
except ValueError as error:
    sys.exit(f"Некорректный IP_ADDR: {error}")
PY

if [[ -z "${TITLE:-}" ]]; then
    log "Название для виртуальной ноды не указано. Будет использовано составное"
    TITLE="Vnode_PrId-'$PROTO_ID'_NId-'$NODE_ID'"
fi

# awg-quick@ передаёт имя интерфейса и ищет конфиг в стандартном каталоге.
CONFIG_DIR="/etc/amnezia/amneziawg"
LEGACY_CONFIG_DIR="/etc/reinar/configs/amneziawg"
install -d -m 0700 "$CONFIG_DIR"

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
    log "Не найден свободный диапазон портов для hopping."
    return 1
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
while [[ -e "$CONFIG_DIR/awg${IDX}.conf" || -e "$LEGACY_CONFIG_DIR/awg${IDX}.conf" ]] ||
      ip link show "awg${IDX}" >/dev/null 2>&1; do
  IDX=$((IDX+1))
done
IFACE="awg${IDX}"
CONFIG_PATH="$CONFIG_DIR/${IFACE}.conf"
SERVICE_NAME="awg-quick@${IFACE}.service"

WG_PORT=$(find_free_port 51820)
read -r RANGE_START RANGE_END <<< "$(find_free_port_range)"

if [[ "$AWG_ROUTING" == 1 ]]; then
    MAIN_IFACE=$(ip "-$IP_VERSION" route show default | awk '/default/ && !iface {iface=$5} END {print iface}')
    if [[ -z "$MAIN_IFACE" ]]; then
        log "Не найден интерфейс для маршрута по умолчанию IPv$IP_VERSION."
        exit 1
    fi
fi

# --- 2. ГЕНЕРАЦИЯ КЛЮЧЕЙ И ПАРАМЕТРОВ ---
PRIVATE_KEY=$(awg genkey)
PUBLIC_KEY=$(echo "$PRIVATE_KEY" | awg pubkey)
NODE_HASH_SALT=$(openssl rand -base64 12)

log "1. Регистрация ноды в панели и получение node_proto_id..."

REG_RESPONSE=$(mktemp)
trap 'rm -f "$REG_RESPONSE"' EXIT
# Для CLI-метрик поле metrics_port служит положительным идентификатором.
REG_BODY=$(jq -n \
    --argjson proto_id "$PROTO_ID" --argjson node_id "$NODE_ID" \
    --arg path "$CONFIG_PATH" --argjson port "$WG_PORT" --argjson metrics_port "$((IDX + 1))" \
    --arg reload "systemctl reload $SERVICE_NAME" --arg metrics "awg show $IFACE dump" \
    --arg title "$TITLE" --arg address "${SUB_NODE_ADDRESS:-}" \
    --arg subnet_key "node_ipv${IP_VERSION}_subnet" --arg subnet "$IP_ADDR" \
    --arg public_key "$PUBLIC_KEY" --arg salt "$NODE_HASH_SALT" \
    --argjson hop_start "$RANGE_START" --argjson hop_end "$RANGE_END" \
    '{
        proto_id: $proto_id,
        node_id: $node_id,
        config_path: $path,
        proto_port: $port,
        metrics_port: $metrics_port,
        reload_core_command: $reload,
        metrics_command: $metrics,
        sub_node_address: (if $address == "" then null else $address end),
        title: $title,
        constant_node_data_obj: {
            ($subnet_key): $subnet,
            node_public_key: $public_key,
            node_hop_start: $hop_start,
            node_hop_end: $hop_end,
            node_hash_salt: $salt
        }
    }')
HTTP_CODE=$(curl -sS --max-time 15 -w "%{http_code}" -o "$REG_RESPONSE" \
    -H "Content-Type: application/json" -d "$REG_BODY" "$PANEL_PROTOCOLS_URL/register")

if [ "$HTTP_CODE" -ne 200 ]; then
    log "\033[31mОшибка регистрации (HTTP $HTTP_CODE): $(cat "$REG_RESPONSE")\033[0m"
    exit 1
fi

NODE_PROTO_ID=$(jq -er '.node_proto_id' "$REG_RESPONSE")
TITLE=$(jq -er '.title' "$REG_RESPONSE")

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
EOF
if [[ "$AWG_ROUTING" == 1 ]]; then
    FIREWALL=iptables
    if [[ "$IP_VERSION" == 6 ]]; then
        FIREWALL=ip6tables
    fi
    POST_UP="$FIREWALL -A FORWARD -i $IFACE -j ACCEPT; $FIREWALL -t nat -A POSTROUTING -s $IP_ADDR -o $MAIN_IFACE -j MASQUERADE; $FIREWALL -t nat -A PREROUTING -p udp --dport $RANGE_START:$RANGE_END -j REDIRECT --to-ports $WG_PORT"
    POST_DOWN="$FIREWALL -D FORWARD -i $IFACE -j ACCEPT; $FIREWALL -t nat -D POSTROUTING -s $IP_ADDR -o $MAIN_IFACE -j MASQUERADE; $FIREWALL -t nat -D PREROUTING -p udp --dport $RANGE_START:$RANGE_END -j REDIRECT --to-ports $WG_PORT"
    cat <<EOF >> "$CONFIG_PATH"
PostUp = $POST_UP
PostDown = $POST_DOWN
EOF
fi

PROTOCOL_CONFIG_CONTENT=$(jq -Rs . "$CONFIG_PATH")

log "2. Запуск юнита $SERVICE_NAME..."
if ! systemctl start "$SERVICE_NAME" >&2 ||
   ! systemctl is-active --quiet "$SERVICE_NAME" ||
   { [[ "$AWG_AUTOSTART" == 1 ]] && ! systemctl enable "$SERVICE_NAME" >&2; }; then
    log "\033[31mСервис $SERVICE_NAME не смог запуститься! Откат...\033[0m"
    systemctl stop "$SERVICE_NAME" || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$CONFIG_PATH"

    # Оповещаем панель о фейле
    ROLLBACK_BODY=$(jq -n \
      --argjson node_proto_id "$NODE_PROTO_ID" \
      '{node_proto_id: $node_proto_id, status: 3}')

    curl -sS --max-time 15 \
         -H "Content-Type: application/json" \
         -d "$ROLLBACK_BODY" "$PANEL_PROTOCOLS_URL/confirm" >/dev/null || true
    exit 1
fi

# 6. Финализация статуса в панели
CONFIRM_BODY=$(jq -n \
  --argjson node_proto_id "$NODE_PROTO_ID" \
  --arg service_name "$SERVICE_NAME" \
  --argjson config_content "$PROTOCOL_CONFIG_CONTENT" \
  '{
    node_proto_id: $node_proto_id,
    status: 2,
    service_name: $service_name,
    config_content: $config_content
  }')

curl -fsS --max-time 15 \
     -H "Content-Type: application/json" \
     -d "$CONFIRM_BODY" "$PANEL_PROTOCOLS_URL/confirm" >/dev/null


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
