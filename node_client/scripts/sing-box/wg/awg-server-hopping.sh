#!/bin/bash

TMP_ID=$1
# Адреса самого сервера внутри туннеля (с маской). Передаются из панели.
# Пример: 10.1.0.1/16
IP_ADDR=$2
# Пример: fd00:1::1/64
IP_VERSION=$3

if [ -z "$TMP_ID" ] || [ -z "$IP_ADDR" ] || [ -z "$IP_VERSION" ]; then
    echo "Ошибка: Необходимы параметры TMP_ID, ip_addr, ip_version!"
    echo "Использование: bash sing-box-wg-install.sh <tmp_id> <ip_addr> <ip_version>"
    exit 1
fi

SINGBOX_BIN="/usr/local/bin/sing-box-awg"
CONFIG_DIR="/etc/sing-box/configs"
CONFIG_PATH="$CONFIG_DIR/${TMP_ID}.json"
PANEL_CALLBACK_URL="http://10.0.0.1/api/node/callback"

mkdir -p "$CONFIG_DIR"


# Функция поиска свободного диапазона портов (размером 100 портов)
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

    # Fallback, если всё занято
    echo "20000 20099"
}

# Функция поиска свободного порта
find_free_port() {
    local port=$1
    while ss -lntu | awk '{print $4}' | grep -q ":$port$"; do
        port=$((port + 1))
    done
    echo $port
}

WG_PORT=$(find_free_port 51820)
METRICS_PORT=$(find_free_port 10085)

echo "Выделен порт для WireGuard: $WG_PORT"
echo "Выделен порт для Метрик: $METRICS_PORT"

# Ищем свободный диапазон для хоппинга
# shellcheck disable=SC2046
# shellcheck disable=SC2162
read RANGE_START RANGE_END <<< $(find_free_port_range)


echo "Выделен внутренний порт для Sing-box: $WG_PORT"
# shellcheck disable=SC1072
# shellcheck disable=SC1073
# shellcheck disable=SC1009
if [ "$IP_VERSION" --eq 4]; then
  iptables -t nat -A PREROUTING -p udp --dport "${RANGE_START}":"${RANGE_END}" -j REDIRECT --to-ports "${WG_PORT}"
fi

if [ "$IP_VERSION" --eq 6]; then
  ip6tables -t nat -A PREROUTING -p udp --dport ${RANGE_START}:${RANGE_END} -j REDIRECT --to-ports ${WG_PORT}
fi
echo "Выделен диапазон портов для Port Hopping: ${RANGE_START}-${RANGE_END}"

# --- ГЕНЕРАЦИЯ КЛЮЧЕЙ СЕРВЕРА ---
# sing-box выдает вывод вида:
# PrivateKey: <base64>
# PublicKey: <base64>
WG_KEYS=$($SINGBOX_BIN generate wg-keypair)
WG_PRIVATE_KEY=$(echo "$WG_KEYS" | grep PrivateKey | awk '{print $2}')
WG_PUBLIC_KEY=$(echo "$WG_KEYS" | grep PublicKey | awk '{print $2}')
NODE_HASH_SALT=$(openssl rand -base64 12)

# --- 2. ГЕНЕРАЦИЯ ПАРАМЕТРОВ ОБФУСКАЦИИ (AWG) ---
# Генерируем уникальный профиль маскировки для каждой ноды
JC=$(( RANDOM % 10 + 3 ))           # от 3 до 12
JMIN=$(( RANDOM % 20 + 40 ))        # от 40 до 59
JMAX=$(( RANDOM % 300 + 700 ))      # от 700 до 999
S1=$(( RANDOM % 100 + 15 ))         # от 15 до 114
S2=$(( RANDOM % 100 + 15 ))         # от 15 до 114

# H1-H4 - большие случайные числа (магические заголовки)
# Bash RANDOM генерирует от 0 до 32767, комбинируем для получения больших int
generate_magic() { echo $(( (RANDOM << 15) | RANDOM )); }
H1=$(generate_magic)
H2=$(generate_magic)
H3=$(generate_magic)
H4=$(generate_magic)
# Генерация конфига Sing-box
cat <<EOF > "$CONFIG_PATH"
{
  "log": {
      "level": "warn"
  },
  "experimental": {
    "v2ray_api": {
      "listen": "127.0.0.1:$METRICS_PORT",
      "stats": {
        "enabled": true,
        "inbounds": [
          "wg-in"
        ],
        "users": []
      }
    }
  },
  "inbounds": [
    {
      "type": "wireguard",
      "tag": "wg-in",
      "listen": "::",
      "listen_port": $WG_PORT,
      "system": false,
      "local_address": [
        "$IP_ADDR",
      ],
      "private_key": "$WG_PRIVATE_KEY",
      "peers": [],
      "jc": $JC,
      "jmin": $JMIN,
      "jmax": $JMAX,
      "s1": $S1,
      "s2": $S2,
      "h1": $H1,
      "h2": $H2,
      "h3": $H3,
      "h4": $H4
    }
  ],
  "outbounds": [
    {
      "type": "direct",
      "tag": "direct"
    }
  ]
}
EOF

# Создание systemd сервиса
SERVICE_PATH="/etc/systemd/system/sing-box-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Sing-box AmneziaWG Node Server Hopping (TMP_ID: ${TMP_ID})
After=network.target nss-lookup.target

[Service]
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=$SINGBOX_BIN run -c $CONFIG_PATH
Restart=on-failure
RestartPreventExitStatus=23
LimitNPROC=10000
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "sing-box-${TMP_ID}"
systemctl restart "sing-box-${TMP_ID}"

# --- ОТПРАВКА CALLBACK ---
# Важно: Мы отправляем WG_PUBLIC_KEY обратно в панель!
# Панель должна сохранить его в constant_node_data_obj,
# чтобы клиенты знали, к какому серверу подключаться.

curl -s -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "tmp_id": "'"$TMP_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "proto_port": '"$WG_PORT"',
           "metrics_port": '"$METRICS_PORT"',
           "status": "installed",
           "node_type": "singbox_wg_hopping",
           "constant_node_data_obj": {
               "node_ipv'"$IP_VERSION"'_subnet": "'"$IP_ADDR"'",
               "node_public_key": "'"$WG_PUBLIC_KEY"'",
               "node_hop_start": '"$RANGE_START"',
               "node_hop_end": '"$RANGE_END"',
               "node_hash_salt": '"$NODE_HASH_SALT"'
           }
         }'

echo "=================================================="
echo "Sing-box WireGuard развернут."
echo "Порт WG: $WG_PORT | Public Key: $WG_PUBLIC_KEY"
echo "=================================================="