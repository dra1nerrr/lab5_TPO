"""
Лабораторная работа №5.
Разработка автотестов для API Redfish с использованием PyTest.

Сценарии:
1. Тест аутентификации в OpenBMC через Redfish API (успешный вход и отказ при неверных данных).
2. Тест получения информации о системе (GET /redfish/v1/Systems/system, проверка Status и PowerState).
3. Тест управления питанием (включение/выключение сервера через ComputerSystem.Reset).
4. Тест на соответствие температуры CPU норме в соответствии со спецификацией Redfish Thermal.
5. Тест на соответствие показаний датчиков CPU между Redfish API и IPMI.
"""

import logging
import pytest
import requests

from redfish_mock_service import get_ipmi_cpu_temperature

logger = logging.getLogger("RedfishTests")


class TestRedfishAPI:
    """Набор тестов для проверки REST API стандарта DMTF Redfish в OpenBMC."""

    # -------------------------------------------------------------------------
    # 1. Сценарий: Аутентификация в OpenBMC через Redfish API
    # -------------------------------------------------------------------------
    def test_01_authentication_success(self, bmc_base_url, bmc_credentials, raw_session):
        """
        Проверка создания сессии в OpenBMC через Redfish API:
        - Отправка POST-запроса на /redfish/v1/SessionService/Sessions.
        - Проверка кода ответа (201 Created или 200 OK).
        - Проверка наличия токена сессии в ответе (заголовок X-Auth-Token или тело ответа).
        - Корректное закрытие сессии (DELETE).
        """
        login_url = f"{bmc_base_url}/redfish/v1/SessionService/Sessions"
        payload = {
            "UserName": bmc_credentials["username"],
            "Password": bmc_credentials["password"]
        }

        logger.info(f"Тест 1: Аутентификация пользователя '{payload['UserName']}' по адресу {login_url}")
        response = raw_session.post(login_url, json=payload, timeout=5.0)

        logger.info(f"Статус ответа: {response.status_code}")
        assert response.status_code in (200, 201), (
            f"Ожидался код 200 или 201, получен {response.status_code}. Ответ: {response.text}"
        )

        # Проверка токена сессии
        token = response.headers.get("X-Auth-Token")
        data = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
        if not token:
            token = data.get("Token") or data.get("Id")

        assert token, "Токен сессии X-Auth-Token не найден ни в заголовках, ни в теле ответа!"
        logger.info(f"Успешно получен токен сессии: {token[:12]}...")

        # Проверка идентификатора сессии и очистка (DELETE)
        session_uri = response.headers.get("Location") or data.get("@odata.id")
        if session_uri:
            if not session_uri.startswith("http"):
                delete_url = f"{bmc_base_url}{session_uri}"
            else:
                delete_url = session_uri

            del_resp = raw_session.delete(delete_url, headers={"X-Auth-Token": token}, timeout=3.0)
            assert del_resp.status_code in (200, 204), f"Ошибка при удалении сессии: {del_resp.status_code}"
            logger.info("Сессия успешно закрыта через DELETE.")

    def test_01_b_authentication_invalid_credentials(self, bmc_base_url, raw_session):
        """
        Негативный тест аутентификации:
        - Попытка входа с заведомо неверным паролем.
        - Проверка кода ответа 401 Unauthorized.
        - Проверка отсутствия токена в ответе.
        """
        login_url = f"{bmc_base_url}/redfish/v1/SessionService/Sessions"
        payload = {
            "UserName": "root",
            "Password": "WrongInvalidPassword_999!"
        }

        logger.info(f"Негативный тест аутентификации: отправка неверного пароля на {login_url}")
        response = raw_session.post(login_url, json=payload, timeout=5.0)

        assert response.status_code == 401, (
            f"Ожидался код 401 Unauthorized при неверных данных, получен {response.status_code}"
        )
        assert "X-Auth-Token" not in response.headers, "Сервер вернул X-Auth-Token при неверных учётных данных!"
        logger.info("Сервер корректно отклонил запрос с кодом 401 Unauthorized.")

    # -------------------------------------------------------------------------
    # 2. Сценарий: Получение информации о системе (ComputerSystem)
    # -------------------------------------------------------------------------
    def test_02_get_system_info(self, bmc_base_url, redfish_session):
        """
        Тест получения информации о сервере:
        - Отправка GET-запроса на /redfish/v1/Systems/system.
        - Проверка статус-кода 200 OK.
        - Проверка наличия обязательных полей: 'Status' и 'PowerState'.
        - Проверка структуры 'Status' (наличие 'State' и 'Health').
        """
        system_url = f"{bmc_base_url}/redfish/v1/Systems/system"
        logger.info(f"Тест 2: Запрос информации о системе GET {system_url}")

        response = redfish_session.get(system_url, timeout=5.0)
        assert response.status_code == 200, f"Ожидался HTTP 200, получен {response.status_code}: {response.text}"

        data = response.json()

        # Проверка обязательных полей по заданию
        assert "Status" in data, "В ответе отсутствует обязательное поле 'Status'"
        assert "PowerState" in data, "В ответе отсутствует обязательное поле 'PowerState'"

        status = data["Status"]
        assert "State" in status, "В объекте 'Status' отсутствует поле 'State'"
        assert "Health" in status, "В объекте 'Status' отсутствует поле 'Health'"

        # Проверка допустимых значений
        allowed_power_states = ["On", "Off", "PoweringOn", "PoweringOff", "Paused"]
        assert data["PowerState"] in allowed_power_states, (
            f"Недопустимое значение PowerState: {data['PowerState']}. Допустимые: {allowed_power_states}"
        )

        logger.info(f"Система: {data.get('Name', 'Unknown')}, Модель: {data.get('Model', 'N/A')}")
        logger.info(f"Состояние питания: PowerState={data['PowerState']}")
        logger.info(f"Статус работоспособности: State={status['State']}, Health={status['Health']}")

    # -------------------------------------------------------------------------
    # 3. Сценарий: Управление питанием (включение/выключение сервера)
    # -------------------------------------------------------------------------
    def test_03_power_management_reset(self, bmc_base_url, redfish_session):
        """
        Тест управления питанием сервера:
        - Отправка POST-запроса на /redfish/v1/Systems/system/Actions/ComputerSystem.Reset
          с параметром {"ResetType": "On"}.
        - Проверка, что ответ содержит код 202 Accepted (или 200/204).
        - Запрос обновленного состояния системы (GET /redfish/v1/Systems/system).
        - Проверка, что статус системы изменился на 'PowerState': 'On'.
        """
        action_url = f"{bmc_base_url}/redfish/v1/Systems/system/Actions/ComputerSystem.Reset"
        system_url = f"{bmc_base_url}/redfish/v1/Systems/system"

        # Шаг 1: Включение питания сервера
        logger.info(f"Тест 3: Отправка команды включения сервера POST {action_url} with ResetType='On'")
        payload = {"ResetType": "On"}
        resp_on = redfish_session.post(action_url, json=payload, timeout=5.0)

        assert resp_on.status_code in (200, 202, 204), (
            f"Ожидался код 202 Accepted (или 200/204), получен {resp_on.status_code}. Ответ: {resp_on.text}"
        )
        logger.info(f"Команда включения принята сервером с кодом HTTP {resp_on.status_code}")

        # Шаг 2: Проверка обновленного статуса PowerState
        resp_sys = redfish_session.get(system_url, timeout=5.0)
        assert resp_sys.status_code == 200
        sys_data = resp_sys.json()
        power_state = sys_data.get("PowerState")
        assert power_state == "On", f"Статус питания не перешел в 'On'! Текущий: {power_state}"
        logger.info("Успешно подтверждено изменение статуса системы на 'PowerState': 'On'")

        # Шаг 3 (дополнительно): Проверка выключения сервера для полноты жизненного цикла
        logger.info("Проверка команды выключения сервера ResetType='ForceOff'")
        resp_off = redfish_session.post(action_url, json={"ResetType": "ForceOff"}, timeout=5.0)
        assert resp_off.status_code in (200, 202, 204)

        resp_sys_off = redfish_session.get(system_url, timeout=5.0)
        assert resp_sys_off.json().get("PowerState") == "Off"
        logger.info("Успешно подтверждено изменение статуса системы на 'PowerState': 'Off'")

        # Возвращаем в On
        redfish_session.post(action_url, json={"ResetType": "On"}, timeout=5.0)

    # -------------------------------------------------------------------------
    # 4. Сценарий: Тест на соответствие температуры CPU норме в Redfish
    # -------------------------------------------------------------------------
    def test_04_cpu_temperature_normal_redfish(self, bmc_base_url, redfish_session):
        """
        Тест на соответствие температуры процессора (CPU) норме согласно схеме DMTF Redfish Thermal:
        - Запрос ресурса Thermal (/redfish/v1/Chassis/chassis/Thermal).
        - Проверка статус-кода 200 OK.
        - Поиск сенсоров CPU в коллекции Temperatures.
        - Проверка наличия показателя ReadingCelsius.
        - Проверка, что температура находится в допустимом диапазоне (выше 0°C и ниже критического порога).
        - Проверка статуса сенсора: Health == 'OK', State == 'Enabled'.
        """
        thermal_url = f"{bmc_base_url}/redfish/v1/Chassis/chassis/Thermal"
        logger.info(f"Тест 4: Запрос тепловых параметров GET {thermal_url}")

        response = redfish_session.get(thermal_url, timeout=5.0)
        assert response.status_code == 200, f"Ошибка запроса Thermal ресурса: HTTP {response.status_code}"

        thermal_data = response.json()
        assert "Temperatures" in thermal_data, "В ресурсе Thermal отсутствует массив 'Temperatures'"

        temperatures = thermal_data["Temperatures"]
        assert len(temperatures) > 0, "Коллекция температурных датчиков пуста!"

        cpu_sensors = [t for t in temperatures if "cpu" in t.get("Name", "").lower() or t.get("PhysicalContext") == "CPU"]
        assert len(cpu_sensors) > 0, "Датчики температуры CPU не найдены в коллекции Thermal"

        for sensor in cpu_sensors:
            sensor_name = sensor.get("Name", "CPU Sensor")
            temp = sensor.get("ReadingCelsius")

            assert temp is not None, f"У датчика '{sensor_name}' отсутствует поле ReadingCelsius"
            assert isinstance(temp, (int, float)), f"ReadingCelsius должен быть числом, получено {type(temp)}"

            # Проверка пороговых значений
            upper_non_crit = sensor.get("UpperThresholdNonCritical", 75.0)
            upper_crit = sensor.get("UpperThresholdCritical", 85.0)

            logger.info(
                f"Сенсор: '{sensor_name}' | Температура: {temp} °C "
                f"(Порог предупреждения: {upper_non_crit} °C, Критический: {upper_crit} °C)"
            )

            # Проверка нахождения в рабочем диапазоне нормы
            assert 0.0 < temp < upper_crit, (
                f"Температура {temp} °C датчика '{sensor_name}' выходит за допустимые пределы (0.0..{upper_crit} °C)!"
            )

            # Проверка статуса здоровья компонента
            status = sensor.get("Status", {})
            assert status.get("Health") == "OK", f"Статус здоровья датчика '{sensor_name}' не 'OK': {status}"
            assert status.get("State") == "Enabled", f"Состояние датчика '{sensor_name}' не 'Enabled': {status}"

        logger.info("[УСПЕХ] Все датчики CPU находятся в пределах нормы и имеют статус Health=OK.")

    # -------------------------------------------------------------------------
    # 5. Сценарий: Тест на соответствие датчиков CPU в Redfish и IPMI
    # -------------------------------------------------------------------------
    def test_05_cpu_sensors_redfish_vs_ipmi_coherence(self, bmc_base_url, redfish_session):
        """
        Тест на соответствие датчиков CPU в Redfish и IPMI:
        - Получение температуры CPU0 через Redfish REST API (ReadingCelsius).
        - Получение температуры CPU0 через интерфейс IPMI (SDR / Sensor).
        - Проверка эквивалентности показаний двух протоколов (расхождение <= 1.0 °C).
        - Подтверждение когерентности телеметрии OpenBMC D-Bus между Redfish и IPMI стеком.
        """
        logger.info("Тест 5: Сравнение показаний термодатчиков CPU между Redfish API и IPMI")

        # Шаг 1: Получение значения из Redfish API
        thermal_url = f"{bmc_base_url}/redfish/v1/Chassis/chassis/Thermal"
        resp_redfish = redfish_session.get(thermal_url, timeout=5.0)
        assert resp_redfish.status_code == 200

        redfish_temp = None
        for t in resp_redfish.json().get("Temperatures", []):
            if "cpu0" in t.get("Name", "").lower() or t.get("MemberId") == "0":
                redfish_temp = float(t.get("ReadingCelsius"))
                break

        assert redfish_temp is not None, "Не удалось получить температуру CPU0 из Redfish API"
        logger.info(f"Температура CPU0, полученная через Redfish API: {redfish_temp} °C")

        # Шаг 2: Получение значения через IPMI
        ipmi_temp = get_ipmi_cpu_temperature(host="127.0.0.1", port=2623)
        assert ipmi_temp is not None, "Не удалось получить температуру CPU0 через протокол IPMI"
        logger.info(f"Температура CPU0, полученная через IPMI (sdr/sensor): {ipmi_temp} °C")

        # Шаг 3: Проверка сходимости показаний
        diff = abs(redfish_temp - ipmi_temp)
        logger.info(f"Разница показаний Redfish и IPMI: {diff:.3f} °C (допустимо: <= 1.0 °C)")

        assert diff <= 1.0, (
            f"Рассинхронизация датчиков! Redfish: {redfish_temp} °C, IPMI: {ipmi_temp} °C. "
            f"Разница {diff} °C превышает допустимый порог 1.0 °C."
        )

        logger.info(
            f"[УСПЕХ] Датчики Redfish ({redfish_temp} °C) и IPMI ({ipmi_temp} °C) "
            "полностью согласованы и когерентны."
        )
