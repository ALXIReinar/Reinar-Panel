#!/bin/bash
set -euo pipefail

case "${1:-}" in
  ""|--kernel) backend=kernel ;;
  --userspace) backend=userspace ;;
  *)
    echo "Использование: $0 [--kernel|--userspace]" >&2
    exit 2
    ;;
esac

# Проверка прав root
if [ "$EUID" -ne 0 ]; then
  echo "Ошибка: Скрипт должен быть запущен с правами root."
  exit 1
fi

if [[ "$backend" == kernel ]]; then
  headers="linux-headers-$(uname -r)"
else
  if [[ ! -c /dev/net/tun ]]; then
    modprobe tun
  fi
  if [[ ! -c /dev/net/tun ]]; then
    echo "Для amneziawg-go требуется устройство /dev/net/tun." >&2
    exit 1
  fi
fi

echo "1. Установка базовых зависимостей..."
apt-get update
if [[ "$backend" == kernel && ! -e "/lib/modules/$(uname -r)/build/Makefile" ]]; then
  apt-get install -y "$headers"
fi
apt-get install -y software-properties-common iproute2 iptables curl jq openssl

echo "2. Подключение репозитория AmneziaWG..."
# Для Ubuntu используется официальный PPA
add-apt-repository -y ppa:amnezia/ppa
apt-get update

echo "3. Установка ядра и утилит AmneziaWG..."
if [[ "$backend" == userspace ]]; then
  apt-get install -y --no-install-recommends amneziawg-tools
  if ! command -v go >/dev/null; then
    apt-get install -y golang-go
  fi
  GOBIN=/usr/local/bin GOTOOLCHAIN=auto go install github.com/amnezia-vpn/amneziawg-go/v3@v3.1.20260828
else
  apt-get install -y dkms amneziawg-dkms amneziawg-tools
  modprobe amneziawg

  echo "4. Настройка маршрутизации (IP Forwarding)..."
  cat > /etc/sysctl.d/99-amneziawg-forward.conf <<EOF
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF
  sysctl -p /etc/sysctl.d/99-amneziawg-forward.conf
fi

echo "✅ AmneziaWG успешно установлен!"
awg --version
