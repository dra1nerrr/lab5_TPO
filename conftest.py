"""
Конфигурация pytest и фикстуры для тестирования OpenBMC Redfish API.
Лабораторная работа №5.
"""

import logging
import os
import urllib3
import pytest
import requests

from redfish_mock_service import start_mock_redfish_server

# Отключаем предупреждения о самоподписанных сертификатах SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("RedfishTests")


def pytest_addoption(parser):
    """Регистрация параметров командной строки pytest."""
    parser.addoption(
        "--bmc-url",
        action="store",
        default=os.getenv("OPENBMC_URL", ""),
        help="Базовый URL Redfish API OpenBMC (например https://127.0.0.1:2443 или http://127.0.0.1:18443)"
    )
    parser.addoption(
        "--bmc-user",
        action="store",
        default=os.getenv("OPENBMC_USER", "root"),
        help="Имя пользователя для авторизации в BMC (по умолчанию: root)"
    )
    parser.addoption(
        "--bmc-pass",
        action="store",
        default=os.getenv("OPENBMC_PASS", "0penBmc"),
        help="Пароль для авторизации в BMC (по умолчанию: 0penBmc)"
    )
    parser.addoption(
        "--force-mock",
        action="store_true",
        default=False,
        help="Принудительно использовать встроенный сервис-эмулятор OpenBMC Redfish"
    )


@pytest.fixture(scope="session")
def bmc_base_url(request):
    """
    Определяет базовый URL для тестирования Redfish API.
    Если реальный BMC не запущен или недоступен, автоматически запускает локальный сервис-эмулятор.
    """
    custom_url = request.config.getoption("--bmc-url")
    force_mock = request.config.getoption("--force-mock")

    if force_mock:
        url = start_mock_redfish_server(18443)
        logger.info(f"Запущен локальный сервис-эмулятор Redfish API: {url}")
        return url

    if custom_url:
        return custom_url.rstrip("/")

    # Проверяем доступность QEMU OpenBMC на стандартном порту 2443
    candidate_urls = [
        "https://127.0.0.1:2443",
        "http://127.0.0.1:8080"
    ]
    for cand in candidate_urls:
        try:
            resp = requests.get(f"{cand}/redfish/v1", verify=False, timeout=1.0)
            if resp.status_code in (200, 401):
                logger.info(f"Обнаружен активный OpenBMC на {cand}")
                return cand
        except Exception:
            continue

    # Если внешний BMC недоступен, поднимаем встроенный эмулятор OpenBMC Romulus
    url = start_mock_redfish_server(18443)
    logger.info(f"Реальный BMC не обнаружен. Запущен встроенный эмулятор OpenBMC: {url}")
    return url


@pytest.fixture(scope="session")
def bmc_credentials(request):
    """Возвращает валидные учётные данные OpenBMC."""
    return {
        "username": request.config.getoption("--bmc-user"),
        "password": request.config.getoption("--bmc-pass")
    }


@pytest.fixture(scope="function")
def raw_session():
    """Возвращает чистую HTTP-сессию без заголовков авторизации."""
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json"
    })
    yield session
    session.close()


@pytest.fixture(scope="function")
def redfish_session(bmc_base_url, bmc_credentials):
    """
    Фикстура аутентифицированной сессии Redfish.
    Создает сессию через POST /redfish/v1/SessionService/Sessions,
    добавляет токен X-Auth-Token в заголовки всех запросов,
    а после завершения теста удаляет сессию (teardown) через DELETE.
    """
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json"
    })

    login_url = f"{bmc_base_url}/redfish/v1/SessionService/Sessions"
    payload = {
        "UserName": bmc_credentials["username"],
        "Password": bmc_credentials["password"]
    }

    logger.info(f"Создание сессии Redfish: POST {login_url}")
    response = session.post(login_url, json=payload, timeout=5.0)

    assert response.status_code in (200, 201), (
        f"Не удалось создать сессию Redfish. HTTP {response.status_code}: {response.text}"
    )

    # Извлечение токена сессии
    token = response.headers.get("X-Auth-Token")
    if not token and response.headers.get("Content-Type", "").startswith("application/json"):
        data = response.json()
        token = data.get("Token") or data.get("Id")

    assert token, "Токен аутентификации отсутствует в ответе сервера"
    session.headers.update({"X-Auth-Token": token})

    # Определение URI сессии для корректного удаления при teardown
    session_uri = response.headers.get("Location")
    if not session_uri and response.headers.get("Content-Type", "").startswith("application/json"):
        data = response.json()
        session_uri = data.get("@odata.id")

    logger.info(f"Сессия Redfish успешно открыта. Токен: {token[:12]}..., URI: {session_uri}")

    # Передача подготовленной сессии в тест
    yield session

    # Teardown: закрытие и удаление сессии на сервере BMC
    if session_uri:
        if not session_uri.startswith("http"):
            delete_url = f"{bmc_base_url}{session_uri}"
        else:
            delete_url = session_uri

        logger.info(f"Завершение сессии Redfish (teardown): DELETE {delete_url}")
        try:
            del_resp = session.delete(delete_url, timeout=3.0)
            logger.info(f"Сессия удалена, код ответа: {del_resp.status_code}")
        except Exception as e:
            logger.warning(f"Ошибка при удалении сессии: {e}")

    session.close()
