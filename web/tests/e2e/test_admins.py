import pytest
from uuid import uuid4


def _new_creds():
    """Генерирует валидные учётные данные для тестов"""
    login = f"test_{uuid4().hex[:8]}"  # Короткий логин без домена
    return {"login": login, "passw": "TestPass123!"}  # Валидный пароль: 8+ символов, 1 заглавная, 1 цифра, 1 спецсимвол


@pytest.mark.asyncio
async def test_sign_up_then_login_and_logout(client):
    """Тест регистрации, входа и выхода администратора"""
    creds = _new_creds()
    
    # Проверяем, что используется настоящее хеширование (Argon2)
    from web.config_dir.config import encryption
    hashed = encryption.hash("probe")
    assert hashed.startswith("$argon2"), "Should use real Argon2 hashing"

    # Регистрация
    reg = await client.post("/api/v1/server/admins/sign_up", json=creds)
    assert reg.status_code == 200
    assert reg.json()["success"] is True

    # Вход
    login = await client.post("/api/v1/public/admins/login", json=creds)
    assert login.status_code == 200
    assert "access_token" in login.cookies and "refresh_token" in login.cookies

    # Выход
    logout = await client.put("/api/v1/private/admins/logout", cookies=login.cookies)
    assert logout.status_code == 200
    assert logout.json()["success"] is True
    
    # Проверяем, что токены удалены из cookies
    # После delete_cookie токены либо отсутствуют, либо пустые
    assert "access_token" not in logout.cookies, "access_token should be removed after logout"
    assert "refresh_token" not in logout.cookies, "refresh_token should be removed after logout"


@pytest.mark.asyncio
async def test_sign_up_duplicate_login(client):
    """Тест регистрации с дублирующимся логином"""
    creds = _new_creds()
    
    # Первая регистрация
    reg1 = await client.post("/api/v1/server/admins/sign_up", json=creds)
    assert reg1.status_code == 200
    assert reg1.json()["success"] is True
    
    # Повторная регистрация с тем же логином
    reg2 = await client.post("/api/v1/server/admins/sign_up", json=creds)
    assert reg2.status_code == 204  # В вашем API конфликт возвращает 204
    assert reg2.json()["success"] is False


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    """Тест входа с неправильным паролем"""
    creds = _new_creds()
    
    # Регистрация
    await client.post("/api/v1/server/admins/sign_up", json=creds)
    
    # Попытка входа с неправильным паролем
    bad = {**creds, "passw": "WrongPass123!"}
    resp = await client.post("/api/v1/public/admins/login", json=bad)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_show_seances(client):
    """Тест получения списка активных сессий администратора"""
    creds = _new_creds()
    
    # Регистрация
    reg_resp = await client.post("/api/v1/server/admins/sign_up", json=creds)
    assert reg_resp.status_code == 200
    
    # Вход
    login_resp = await client.post("/api/v1/public/admins/login", json=creds)
    assert login_resp.status_code == 200
    cookies = login_resp.cookies
    
    # Извлекаем session_id из access_token
    import jwt
    access_token = cookies.get("access_token")
    decoded = jwt.decode(access_token, options={"verify_signature": False})
    session_id = decoded.get("s_id")
    
    # Устанавливаем правильные значения в middleware
    client.app.state.test_admin_id = 2  # ID зарегистрированного админа
    client.app.state.test_session_id = session_id  # Реальный session_id из токена

    # Получение списка сессий
    resp = await client.post("/api/v1/private/admins/seances", cookies=cookies)
    assert resp.status_code == 200

    data = resp.json()
    assert "seances" in data, "Response should contain 'seances' field"
    assert isinstance(data["seances"], list), "Seances should be a list"
    # Должна быть хотя бы одна сессия (текущая)
    assert len(data["seances"]) >= 1, "Should have at least one active session"


@pytest.mark.asyncio
async def test_set_new_password(client, seed_info):
    """Тест смены пароля администратора"""
    # Используем базового админа из seed
    test_admin_id = seed_info["admin_id"]
    old_password = seed_info["admin_pass"]
    test_login = seed_info["admin_login"]

    # Меняем пароль
    new_password = "NewPass456!"
    resp = await client.put(
        "/api/v1/server/admins/passw/set_new_passw",
        json={"admin_id": test_admin_id, "passw": new_password}
    )
    assert resp.status_code == 200
    
    data = resp.json()
    assert data["success"] is True, "Password update should succeed"
    assert "message" in data, "Response should contain success message"

    # Проверяем, что старый пароль не работает
    old_login = await client.post(
        "/api/v1/public/admins/login",
        json={"login": test_login, "passw": old_password}
    )
    assert old_login.status_code == 401, "Old password should not work"

    # Проверяем, что новый пароль работает
    new_login = await client.post(
        "/api/v1/public/admins/login",
        json={"login": test_login, "passw": new_password}
    )
    assert new_login.status_code == 200, "New password should work"
    assert "access_token" in new_login.cookies, "Should receive access token"


@pytest.mark.asyncio
async def test_set_new_password_hashes_password(client, seed_info):
    """Тест проверки правильного хеширования пароля при смене"""
    test_admin_id = seed_info["admin_id"]
    test_login = seed_info["admin_login"]
    new_password = "Hashed@Pass789"

    # Меняем пароль
    resp = await client.put(
        "/api/v1/server/admins/passw/set_new_passw",
        json={"admin_id": test_admin_id, "passw": new_password}
    )
    assert resp.status_code == 200

    # Проверяем, что новый пароль работает (что доказывает правильное хеширование)
    new_login = await client.post(
        "/api/v1/public/admins/login",
        json={"login": test_login, "passw": new_password}
    )
    assert new_login.status_code == 200, "Hashed password should work for login"
    assert "access_token" in new_login.cookies, "Should receive access token"