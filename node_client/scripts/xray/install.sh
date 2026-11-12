#!/bin/bash


XRAY_BIN_DIR="/usr/local/bin"
XRAY_SHARE_DIR="/usr/local/share/xray"
XRAY_CONF_DIR="/etc/xray/configs" # Здесь будем хранить наши уникальные конфиги

# Создаем директории
mkdir -p "$XRAY_BIN_DIR" "$XRAY_SHARE_DIR" "$XRAY_CONF_DIR"

if [ ! -f "$XRAY_BIN_DIR/xray" ]; then
    echo "Скачиваем Xray Core..."
    # Получаем последнюю версию
    TAG=$(curl -sL "https://api.github.com/repos/XTLS/Xray-core/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
    DOWNLOAD_URL="https://github.com/XTLS/Xray-core/releases/download/${TAG}/Xray-linux-64.zip"

    wget -qO /tmp/xray.zip "$DOWNLOAD_URL"
    unzip -q /tmp/xray.zip -d /tmp/xray_ext

    mv /tmp/xray_ext/xray "$XRAY_BIN_DIR/xray"
    mv /tmp/xray_ext/*.dat "$XRAY_SHARE_DIR/"

    chmod +x "$XRAY_BIN_DIR/xray"
    rm -rf /tmp/xray.zip /tmp/xray_ext
    echo "Xray Core $TAG установлен."
else
    echo "Xray Core уже установлен."
fi