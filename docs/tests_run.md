# Команды для запуска тестов и отчёта по покрытию

**Все команды работают только из корневой папки проекта**

## Admin Panel(`web/tests`)

### `Test Run`

> python -m pytest web/tests

### `Coverage Run`

> python -m pytest web/tests --cov=web --cov-config=web/.coveragerc --cov-report=html --cov-report=term

## Sub Service(`web/sub/tests`)

### `Test Run`

> python -m pytest web/sub/tests

### `Coverage Run`

> python -m pytest web/sub/tests --cov=web/sub --cov-config=web/sub/.coveragerc --cov-report=html --cov-report=term

## Node Client(`node_client/tests`)

### `Test Run`

Настоящее ядро впн-клиента. Должен быть запущен `docker`

> python -m pytest node_client/tests --mode real --vpn-core vless

Если без докера. 

> python -m pytest node_client/tests --mode mock --vpn-core vless

### `Coverage Run`. Рекомендуется запуск с настоящим ядром (нужен `docker`)

> python -m pytest node_client/tests --mode real --vpn-core vless --cov=node_client --cov-config=node_client/.coveragerc --cov-report=html --cov-report=term
