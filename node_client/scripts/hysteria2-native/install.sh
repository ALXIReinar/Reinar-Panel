#!/bin/bash
set -e

if [ "$EUID" -ne 0 ]; then
  echo "Ошибка: Скрипт должен быть запущен с правами root."
  exit 1
fi

echo "1. Установка базовых зависимостей..."
apt-get update
apt-get install -y curl wget jq iptables iptables-persistent iproute2 openssl libcap2-bin

echo "2. Определение архитектуры системы..."
ARCH=$(uname -m)
case $ARCH in
    x86_64) HY_ARCH="amd64" ;;
    aarch64) HY_ARCH="arm64" ;;
    *) echo "Ошибка: Неподдерживаемая архитектура $ARCH"; exit 1 ;;
esac

echo "3. Скачивание актуальной версии Hysteria 2..."
# Получаем прямую ссылку на бинарник последней версии с GitHub
LATEST_URL=$(curl -s https://api.github.com/repos/apernet/hysteria/releases/latest | grep "browser_download_url.*linux-$HY_ARCH\"" | cut -d : -f 2,3 | tr -d \" | tr -d ' ')

if [ -z "$LATEST_URL" ]; then
    echo "Ошибка: Не удалось получить ссылку на скачивание."
    exit 1
fi

wget -O /usr/local/bin/hysteria "$LATEST_URL"
chmod +x /usr/local/bin/hysteria


echo "✅ Hysteria 2 успешно установлена!"
hysteria version