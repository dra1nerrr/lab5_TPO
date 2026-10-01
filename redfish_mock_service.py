"""
Сервис-эмулятор OpenBMC Redfish API и IPMI для лабораторной работы №5.
Реализует REST API стандарта DMTF Redfish v1 (bmcweb) и интерфейс IPMI SDR/Sensor.
"""

import json
import logging
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

logger = logging.getLogger("RedfishServer")

class MockBMCState:
    """Хранилище состояния виртуального BMC (Romulus OpenBMC)."""
    def __init__(self):
        self.power_state = "Off"
        self.system_health = "OK"
        self.system_state = "Enabled"
        self.cpu0_temp = 42.5
        self.cpu1_temp = 45.0
        self.ambient_temp = 24.0
        self.sessions = {}  # token -> session_data
        self.valid_user = "root"
        self.valid_pass = "0penBmc"

bmc_state = MockBMCState()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class RedfishHTTPRequestHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP-запросов Redfish API стандарта DMTF."""

    def log_message(self, format, *args):
        # Отключаем дефолтный шумный вывод в stderr
        pass

    def _send_json(self, status_code: int, data: dict, extra_headers: dict = None):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status_code: int, extra_headers: dict = None):
        self.send_response(status_code)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()

    def _read_json_body(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            raw = self.rfile.read(content_length).decode("utf-8")
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}

    def _check_auth(self) -> bool:
        """Проверка наличия валидного токена сессии в заголовке X-Auth-Token."""
        token = self.headers.get("X-Auth-Token")
        if not token:
            # Поддержка Basic Auth для curl -u root:0penBmc
            auth_header = self.headers.get("Authorization")
            if auth_header and auth_header.startswith("Basic "):
                import base64
                creds = base64.b64decode(auth_header[6:]).decode("utf-8", errors="ignore")
                if creds == f"{bmc_state.valid_user}:{bmc_state.valid_pass}":
                    return True
            return False
        return token in bmc_state.sessions

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = self.path.rstrip("/")
        if not path:
            path = "/"

        # Публичный корень сервиса DMTF Redfish
        if path in ("/redfish", "/redfish/v1"):
            self._send_json(200, {
                "@odata.type": "#ServiceRoot.v1_5_0.ServiceRoot",
                "Id": "RootService",
                "Name": "Root Service",
                "RedfishVersion": "1.8.0",
                "UUID": "7c823f65-4e78-4395-8d5f-97217db5679a",
                "SessionService": {"@odata.id": "/redfish/v1/SessionService"},
                "Systems": {"@odata.id": "/redfish/v1/Systems"},
                "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
                "Managers": {"@odata.id": "/redfish/v1/Managers"}
            })
            return

        # Коллекция сессий
        if path == "/redfish/v1/SessionService":
            self._send_json(200, {
                "@odata.type": "#SessionService.v1_1_8.SessionService",
                "Id": "SessionService",
                "Name": "Session Service",
                "ServiceEnabled": True,
                "SessionTimeout": 3600,
                "Sessions": {"@odata.id": "/redfish/v1/SessionService/Sessions"}
            })
            return

        if path == "/redfish/v1/SessionService/Sessions":
            members = [{"@odata.id": f"/redfish/v1/SessionService/Sessions/{sid}"} for sid in bmc_state.sessions]
            self._send_json(200, {
                "@odata.type": "#SessionCollection.SessionCollection",
                "Name": "Session Collection",
                "Members@odata.count": len(members),
                "Members": members
            })
            return

        # Защищенные эндпоинты: проверяем авторизацию
        if not self._check_auth():
            self._send_json(401, {
                "error": {
                    "code": "Base.1.0.GeneralError",
                    "message": "Authentication required. Provide valid X-Auth-Token header or Basic Auth credentials."
                }
            })
            return

        # Системная информация
        if path == "/redfish/v1/Systems":
            self._send_json(200, {
                "@odata.type": "#ComputerSystemCollection.ComputerSystemCollection",
                "Name": "Computer System Collection",
                "Members@odata.count": 1,
                "Members": [{"@odata.id": "/redfish/v1/Systems/system"}]
            })
            return

        if path == "/redfish/v1/Systems/system":
            self._send_json(200, {
                "@odata.type": "#ComputerSystem.v1_13_0.ComputerSystem",
                "Id": "system",
                "Name": "Romulus OpenBMC Host System",
                "SystemType": "Physical",
                "Manufacturer": "OpenBMC",
                "Model": "Romulus POWER9 Server",
                "SerialNumber": "ROMULUS-SIM-2026",
                "PowerState": bmc_state.power_state,
                "Status": {
                    "State": bmc_state.system_state,
                    "Health": bmc_state.system_health
                },
                "ProcessorSummary": {
                    "Count": 2,
                    "Model": "IBM POWER9 (24-core)",
                    "Status": {"State": "Enabled", "Health": "OK"}
                },
                "MemorySummary": {
                    "TotalSystemMemoryGiB": 64,
                    "Status": {"State": "Enabled", "Health": "OK"}
                },
                "Actions": {
                    "#ComputerSystem.Reset": {
                        "target": "/redfish/v1/Systems/system/Actions/ComputerSystem.Reset",
                        "ResetType@Redfish.AllowableValues": [
                            "On",
                            "ForceOff",
                            "GracefulShutdown",
                            "GracefulRestart",
                            "ForceRestart"
                        ]
                    }
                }
            })
            return

        # Шасси и термодатчики
        if path == "/redfish/v1/Chassis":
            self._send_json(200, {
                "@odata.type": "#ChassisCollection.ChassisCollection",
                "Name": "Chassis Collection",
                "Members@odata.count": 1,
                "Members": [{"@odata.id": "/redfish/v1/Chassis/chassis"}]
            })
            return

        if path in ("/redfish/v1/Chassis/chassis", "/redfish/v1/Chassis/chassis/Thermal"):
            self._send_json(200, {
                "@odata.type": "#Thermal.v1_7_1.Thermal",
                "Id": "Thermal",
                "Name": "Thermal Information",
                "Temperatures": [
                    {
                        "@odata.id": "/redfish/v1/Chassis/chassis/Thermal#/Temperatures/0",
                        "MemberId": "0",
                        "Name": "CPU0 Core Temp",
                        "ReadingCelsius": bmc_state.cpu0_temp,
                        "Status": {"State": "Enabled", "Health": "OK"},
                        "UpperThresholdNonCritical": 75.0,
                        "UpperThresholdCritical": 85.0,
                        "UpperThresholdFatal": 95.0,
                        "LowerThresholdNonCritical": 5.0,
                        "MinReadingRangeTemp": 0.0,
                        "MaxReadingRangeTemp": 127.0,
                        "PhysicalContext": "CPU"
                    },
                    {
                        "@odata.id": "/redfish/v1/Chassis/chassis/Thermal#/Temperatures/1",
                        "MemberId": "1",
                        "Name": "CPU1 Core Temp",
                        "ReadingCelsius": bmc_state.cpu1_temp,
                        "Status": {"State": "Enabled", "Health": "OK"},
                        "UpperThresholdNonCritical": 75.0,
                        "UpperThresholdCritical": 85.0,
                        "UpperThresholdFatal": 95.0,
                        "LowerThresholdNonCritical": 5.0,
                        "MinReadingRangeTemp": 0.0,
                        "MaxReadingRangeTemp": 127.0,
                        "PhysicalContext": "CPU"
                    },
                    {
                        "@odata.id": "/redfish/v1/Chassis/chassis/Thermal#/Temperatures/2",
                        "MemberId": "2",
                        "Name": "Ambient Ambient Temp",
                        "ReadingCelsius": bmc_state.ambient_temp,
                        "Status": {"State": "Enabled", "Health": "OK"},
                        "UpperThresholdNonCritical": 40.0,
                        "UpperThresholdCritical": 45.0,
                        "UpperThresholdFatal": 50.0,
                        "PhysicalContext": "Intake"
                    }
                ]
            })
            return

        # Сенсоры Sensors
        if path == "/redfish/v1/Chassis/chassis/Sensors":
            self._send_json(200, {
                "@odata.type": "#SensorCollection.SensorCollection",
                "Name": "Sensors Collection",
                "Members": [
                    {"@odata.id": "/redfish/v1/Chassis/chassis/Sensors/temperature_cpu0"},
                    {"@odata.id": "/redfish/v1/Chassis/chassis/Sensors/temperature_cpu1"}
                ]
            })
            return

        if path == "/redfish/v1/Chassis/chassis/Sensors/temperature_cpu0":
            self._send_json(200, {
                "@odata.type": "#Sensor.v1_2_0.Sensor",
                "Id": "temperature_cpu0",
                "Name": "CPU0 Core Temp",
                "Reading": bmc_state.cpu0_temp,
                "ReadingType": "Temperature",
                "ReadingUnits": "Cel",
                "Status": {"State": "Enabled", "Health": "OK"},
                "Thresholds": {
                    "UpperCritical": {"Reading": 85.0},
                    "UpperCaution": {"Reading": 75.0}
                }
            })
            return

        # 404
        self._send_json(404, {"error": {"code": "Base.1.0.ResourceNotFound", "message": f"Resource {path} not found"}})

    def do_POST(self):
        path = self.path.rstrip("/")
        body = self._read_json_body()

        # Создание сессии (Аутентификация в Redfish)
        if path == "/redfish/v1/SessionService/Sessions":
            username = body.get("UserName")
            password = body.get("Password")

            if username == bmc_state.valid_user and password == bmc_state.valid_pass:
                session_id = str(uuid.uuid4())[:8]
                token = f"bmc_token_{session_id}_{int(time.time())}"
                bmc_state.sessions[token] = {
                    "Id": session_id,
                    "UserName": username,
                    "CreatedAt": time.time()
                }

                session_uri = f"/redfish/v1/SessionService/Sessions/{session_id}"
                extra_headers = {
                    "X-Auth-Token": token,
                    "Location": session_uri
                }
                # Стандарт Redfish предписывает 201 Created для POST коллекции сессий
                self._send_json(201, {
                    "@odata.type": "#Session.v1_3_0.Session",
                    "@odata.id": session_uri,
                    "Id": session_id,
                    "Name": "User Session",
                    "Description": "Manager User Session",
                    "UserName": username,
                    "Token": token
                }, extra_headers=extra_headers)
                return
            else:
                self._send_json(401, {
                    "error": {
                        "code": "Base.1.0.AccessDenied",
                        "message": "Invalid credentials provided for OpenBMC Redfish API."
                    }
                })
                return

        # Защищенные POST запросы
        if not self._check_auth():
            self._send_json(401, {
                "error": {
                    "code": "Base.1.0.GeneralError",
                    "message": "Authentication required."
                }
            })
            return

        # Управление питанием (ComputerSystem.Reset)
        if path == "/redfish/v1/Systems/system/Actions/ComputerSystem.Reset":
            reset_type = body.get("ResetType")
            if reset_type == "On":
                bmc_state.power_state = "On"
            elif reset_type in ("ForceOff", "GracefulShutdown"):
                bmc_state.power_state = "Off"
            elif reset_type in ("GracefulRestart", "ForceRestart"):
                bmc_state.power_state = "On"
            else:
                self._send_json(400, {
                    "error": {
                        "code": "Base.1.0.PropertyValueNotInList",
                        "message": f"Unsupported ResetType: {reset_type}"
                    }
                })
                return

            # DMTF стандарт разрешает 202 Accepted или 204 No Content
            self._send_json(202, {
                "@odata.type": "#Task.v1_4_3.Task",
                "Id": "ResetTask",
                "Name": f"Power Reset Task ({reset_type})",
                "TaskState": "Completed",
                "TaskStatus": "OK",
                "Messages": [
                    {
                        "MessageId": "Base.1.0.Success",
                        "Message": f"Server power state successfully transitioned using ResetType {reset_type}."
                    }
                ]
            })
            return

        self._send_json(404, {"error": {"code": "Base.1.0.ResourceNotFound", "message": f"Endpoint {path} not found"}})

    def do_DELETE(self):
        path = self.path.rstrip("/")
        # Удаление сессии
        m = re.match(r"^/redfish/v1/SessionService/Sessions/([a-zA-Z0-9_\-]+)$", path)
        if m:
            session_id = m.group(1)
            # Ищем и удаляем сессию по Id или токену
            token_to_del = None
            for token, sess in bmc_state.sessions.items():
                if sess["Id"] == session_id or token == session_id:
                    token_to_del = token
                    break
            if token_to_del:
                del bmc_state.sessions[token_to_del]
            self._send_empty(204)
            return

        self._send_json(404, {"error": {"code": "Base.1.0.ResourceNotFound", "message": "Session not found"}})


def get_ipmi_cpu_temperature(host: str = "127.0.0.1", port: int = 2623) -> float:
    """
    Эмулирует/вызывает команду IPMI для получения температуры процессора CPU0.
    В реальной системе OpenBMC: ipmitool -I lanplus -H <IP> -p <port> -U root -P 0penBmc sdr type Temperature.
    Возвращает температуру CPU0 в градусах Цельсия.
    """
    # Если запущен реальный OpenBMC на порту port, можно вызвать ipmitool через subprocess:
    import subprocess
    cmd = [
        "wsl", "-d", "Ubuntu", "-e", "ipmitool",
        "-I", "lanplus", "-H", host, "-p", str(port),
        "-U", "root", "-P", "0penBmc", "sdr", "type", "Temperature"
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        if proc.returncode == 0 and "CPU0" in proc.stdout:
            for line in proc.stdout.splitlines():
                if "CPU0" in line or "cpu0" in line:
                    parts = line.split("|")
                    if len(parts) >= 2:
                        val_match = re.search(r"(\d+(\.\d+)?)", parts[1])
                        if val_match:
                            return float(val_match.group(1))
    except Exception:
        pass

    # Синхронизированный ответ из единого слоя D-Bus/State OpenBMC
    return float(bmc_state.cpu0_temp)


_server_instance = None

def start_mock_redfish_server(port: int = 18443) -> str:
    """Запускает встроенный многопоточный Redfish HTTP сервер."""
    global _server_instance
    if _server_instance is not None:
        return f"http://127.0.0.1:{port}"

    server = ThreadedHTTPServer(("127.0.0.1", port), RedfishHTTPRequestHandler)
    _server_instance = server
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.15)
    return f"http://127.0.0.1:{port}"


if __name__ == "__main__":
    url = start_mock_redfish_server(18443)
    print(f"Redfish Mock Service running at {url}")
    print(f"IPMI CPU Temperature query returns: {get_ipmi_cpu_temperature()} °C")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Server stopped.")
