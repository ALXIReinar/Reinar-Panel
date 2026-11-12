#!/bin/bash
set -e

# Проверка прав root
if [ "$EUID" -ne 0 ]; then
  echo "Ошибка: Скрипт должен быть запущен с правами root."
  exit 1
fi

echo "1. Установка базовых зависимостей..."
apt-get update
apt-get install -y software-properties-common iptables ip6tables curl iptables-persistent dkms linux-headers-$(uname -r)

echo "2. Подключение репозитория AmneziaWG..."
# Для Ubuntu используется официальный PPA
add-apt-repository -y ppa:amnezia/ppa
apt-get update

echo "3. Установка ядра и утилит AmneziaWG..."
# amneziawg-dkms собирает модуль под текущее ядро ОС
# amneziawg-tools дает команды awg и awg-quick
apt-get install -y amneziawg-dkms amneziawg-tools

echo "4. Настройка маршрутизации (IP Forwarding)..."
cat > /etc/sysctl.d/99-amneziawg-forward.conf <<EOF
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF
sysctl -p /etc/sysctl.d/99-amneziawg-forward.conf

echo "5. Загрузка модуля ядра..."
# Загружаем модуль без перезагрузки сервера
modprobe amneziawg

echo "✅ AmneziaWG успешно установлен!"
awg --version