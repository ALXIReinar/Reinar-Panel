# WireGuard Setup - Приватная сеть для VPN панели

Инструкция по настройке приватной сети между серверами с помощью WireGuard.

## Архитектура

```
Сервер 1 (Админка)          Сервер 2 (Нода)
10.0.0.1                     10.0.0.2
├── WireGuard сервер         ├── WireGuard клиент
├── Админка :8000            └── Node Client :8001
└── Node Client :8001 (опц)
```

## Быстрая установка

### Шаг 1: Настройка сервера (Админка)

На сервере с админкой:

```bash
cd wireguard_setup
sudo bash install_wg_server.sh
```

Скрипт выведет:
- Публичный IP сервера
- Публичный ключ сервера
- Приватный IP сервера (10.0.0.1)

**Сохраните эту информацию!** Она понадобится для настройки клиента.

### Шаг 2: Настройка клиента (Нода)

На сервере с нодой:

```bash
cd wireguard_setup
sudo bash install_wg_client.sh
```

Скрипт запросит:
- Публичный IP сервера (из шага 1)
- WireGuard порт сервера (по умолчанию 51820)
- Публичный ключ сервера (из шага 1)
- Приватный IP сервера (10.0.0.1)
- Приватный IP этого клиента (например 10.0.0.2)

Скрипт выведет **публичный ключ клиента**.

### Шаг 3: Добавление клиента на сервер

Вернитесь на **сервер** и выполните:

```bash
sudo bash add_wg_client.sh '<CLIENT_PUBLIC_KEY>' '10.0.0.2'
```

Замените `<CLIENT_PUBLIC_KEY>` на ключ из шага 2.

### Шаг 4: Проверка подключения

На клиенте:
```bash
ping 10.0.0.1
```

На сервере:
```bash
ping 10.0.0.2
```

Если ping проходит - приватная сеть работает! 🎉

## Управление WireGuard

### Проверка статуса
```bash
sudo wg show
sudo systemctl status wg-quick@wg0
```

### Перезапуск
```bash
sudo systemctl restart wg-quick@wg0
```

### Остановка
```bash
sudo systemctl stop wg-quick@wg0
```

### Просмотр логов
```bash
sudo journalctl -u wg-quick@wg0 -f
```

## Добавление дополнительных нод

Для каждой новой ноды:

1. На новой ноде: `sudo bash install_wg_client.sh`
   - Используйте следующий IP: 10.0.0.3, 10.0.0.4, и т.д.

2. На сервере: `sudo bash add_wg_client.sh '<NEW_CLIENT_KEY>' '10.0.0.X'`

## Настройка приложений

### Node Client

После установки WireGuard, Node Client должен слушать на приватном IP:

```bash
# В /opt/vpn-node-client/.env.node.prod
NODE_PORT=8001
```

Node Client автоматически биндится на `0.0.0.0`, поэтому доступен по приватному IP.

### Админка

Обновите конфиг админки:

```python
# web/config_dir/.env.api.prod
MY_PRIVATE_IP=10.0.0.1
```

Теперь админка может обращаться к нодам:
- `http://10.0.0.2:8001` - нода 2
- `http://10.0.0.3:8001` - нода 3

## Firewall

WireGuard использует UDP порт 51820. Убедитесь что он открыт:

```bash
# UFW
sudo ufw allow 51820/udp

# iptables
sudo iptables -A INPUT -p udp --dport 51820 -j ACCEPT
```

## Troubleshooting

### Ping не проходит

1. Проверьте что WireGuard запущен на обоих серверах:
   ```bash
   sudo systemctl status wg-quick@wg0
   ```

2. Проверьте что клиент добавлен на сервере:
   ```bash
   sudo wg show
   ```

3. Проверьте firewall:
   ```bash
   sudo ufw status
   ```

### Клиент не подключается

1. Проверьте что публичный IP сервера правильный
2. Проверьте что порт 51820/udp открыт на сервере
3. Проверьте логи:
   ```bash
   sudo journalctl -u wg-quick@wg0 -n 50
   ```

### IP forwarding не работает

```bash
# Проверка
sysctl net.ipv4.ip_forward

# Включение
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf
```

## Безопасность

- ✅ Весь трафик между серверами шифруется
- ✅ Только серверы с правильными ключами могут подключиться
- ✅ Приватная сеть изолирована от интернета
- ⚠️ Не забудьте настроить firewall на нодах (разрешить только с приватной сети)

## Удаление WireGuard

```bash
sudo systemctl stop wg-quick@wg0
sudo systemctl disable wg-quick@wg0
sudo apt-get remove --purge wireguard wireguard-tools
sudo rm -rf /etc/wireguard
```
