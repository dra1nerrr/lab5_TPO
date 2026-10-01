# Лабораторная работа 5. Разработка автотестов для API Redfish с использованием PyTest

## Цель работы
Освоить написание автоматизированных тестов для REST API на примере Redfish API в OpenBMC с использованием фреймворка PyTest. Научиться отправлять HTTP-запросы (GET, POST, DELETE), проверять их корректность, анализировать ответы сервера и валидировать согласованность телеметрии между Redfish и IPMI.

---

## Архитектура и структура проекта
- `conftest.py` — конфигурация PyTest, обработка аргументов CLI (`--bmc-url`, `--bmc-user`, `--bmc-pass`, `--force-mock`), фикстуры инициализации сессии (`redfish_session`), управление жизненным циклом (создание сессии и автоматический teardown через DELETE).
- `test_redfish.py` — тестовый набор с реализацией всех обязательных сценариев лабораторной работы.
- `redfish_mock_service.py` — автономный сервис-эмулятор OpenBMC Redfish API (DMTF Redfish v1) и интерфейса IPMI SDR. Позволяет запускать тесты без необходимости развертывания тяжелого образа ARM QEMU.
- `pytest.ini` — настройки запуска PyTest, уровень логирования и шаблоны вывода.
- `report_lab5.html` — HTML-версия отчета по лабораторной работе.
- `Отчет_Лабораторная_работа_5.pdf` — официальный чистовой отчет в формате PDF.

---

## Покрытые сценарии тестирования (`test_redfish.py`)
1. **Тест аутентификации в OpenBMC через Redfish API (`test_01_authentication_success`, `test_01_b_authentication_invalid_credentials`)**:
   - Отправка `POST /redfish/v1/SessionService/Sessions`.
   - Проверка кода ответа `201 Created` / `200 OK`.
   - Проверка наличия сессионного токена (`X-Auth-Token`) и заголовка `Location`.
   - Проверка отказа в доступе (`401 Unauthorized`) при неверном пароле.
   - Освобождение сессии через `DELETE`.

2. **Тест получения информации о системе (`test_02_get_system_info`)**:
   - Отправка `GET /redfish/v1/Systems/system`.
   - Проверка статус-кода `200 OK`.
   - Проверка наличия и структуры полей `Status` (`State`, `Health`) и `PowerState`.

3. **Тест управления питанием (`test_03_power_management_reset`)**:
   - Отправка `POST /redfish/v1/Systems/system/Actions/ComputerSystem.Reset` с параметром `{"ResetType": "On"}`.
   - Проверка кода ответа `202 Accepted` / `200 OK`.
   - Запрос обновленного состояния сервера и проверка изменения `PowerState` на `"On"`.
   - Проверка отключения питания (`ForceOff`) и переход в `"Off"`.

4. **Тест на соответствие температуры CPU норме в Redfish (`test_04_cpu_temperature_normal_redfish`)**:
   - Запрос схемы DMTF Thermal `GET /redfish/v1/Chassis/chassis/Thermal`.
   - Извлечение данных термодатчиков процессоров (`ReadingCelsius`).
   - Проверка нахождения температуры в рабочем диапазоне (0.0..85.0 °C) и ниже `UpperThresholdCritical`.
   - Проверка статуса датчиков (`Health == "OK"`, `State == "Enabled"`).

5. **Тест на соответствие датчиков CPU в Redfish и IPMI (`test_05_cpu_sensors_redfish_vs_ipmi_coherence`)**:
   - Получение температуры CPU0 через Redfish REST API.
   - Получение показаний датчика через протокол IPMI (`sdr type Temperature`).
   - Проверка согласованности показаний: `abs(redfish_temp - ipmi_temp) <= 1.0 °C`.

---

## Инструкция по запуску

### 1. Установка зависимостей
```bash
pip install pytest requests
```

### 2. Запуск автотестов
Для запуска тестов с автоматическим запуском встроенного эмулятора:
```bash
pytest -v -s
```

Для запуска тестов против реального OpenBMC в QEMU:
```bash
pytest -v -s --bmc-url=https://127.0.0.1:2443 --bmc-user=root --bmc-pass=0penBmc
```

---

## Ссылка на GitHub репозиторий
Разработанные автотесты и отчеты опубликованы в репозитории:
`https://github.com/dra1nerrr/lab5_TPO`
