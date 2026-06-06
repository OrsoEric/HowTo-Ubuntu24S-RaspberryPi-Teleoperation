
"""
uv pip install pyserial
python demo-webserver-teleoperation.py

192.168.1.228:8080
"""

import base64
import hashlib
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import serial
import serial.tools.list_ports

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

HOST = "0.0.0.0"
HTTP_PORT = 8080
WS_PORT = 8765

BAUDRATE = 115200
SEND_PERIOD = 0.25

# --------------------------------------------------
# KEY STATE
# --------------------------------------------------

pressed_keys = set()
key_lock = threading.Lock()

# --------------------------------------------------
# HTML PAGE
# --------------------------------------------------

HTML = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Robot Keyboard Control</title>
</head>
<body>

<h1>Robot Keyboard Control</h1>
<p>Click this page and use WASD or arrow keys.</p>

<script>

const ws = new WebSocket("ws://" + location.hostname + ":{WS_PORT}");

document.addEventListener("keydown", (e) => {{
    ws.send(JSON.stringify({{
        type: "down",
        key: e.key,
        code: e.code
    }}));

    e.preventDefault();
}});

document.addEventListener("keyup", (e) => {{
    ws.send(JSON.stringify({{
        type: "up",
        key: e.key,
        code: e.code
    }}));

    e.preventDefault();
}});

</script>

</body>
</html>
"""

# --------------------------------------------------
# HTTP SERVER
# --------------------------------------------------

class PageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def log_message(self, *args):
        pass

# --------------------------------------------------
# WEBSOCKET
# --------------------------------------------------

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def websocket_handshake(conn):
    data = conn.recv(4096).decode()

    key = None

    for line in data.split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
            break

    if not key:
        return False

    accept = base64.b64encode(
        hashlib.sha1((key + GUID).encode()).digest()
    ).decode()

    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )

    conn.send(response.encode())
    return True


def read_ws_frame(conn):
    hdr = conn.recv(2)

    if len(hdr) < 2:
        return None

    length = hdr[1] & 0x7F

    if length == 126:
        length = int.from_bytes(conn.recv(2), "big")
    elif length == 127:
        length = int.from_bytes(conn.recv(8), "big")

    mask = conn.recv(4)
    payload = bytearray(conn.recv(length))

    for i in range(length):
        payload[i] ^= mask[i % 4]

    return payload.decode()


def websocket_client(conn, addr):
    try:
        if not websocket_handshake(conn):
            return

        print("keyboard connected:", addr)

        while True:
            msg = read_ws_frame(conn)

            if msg is None:
                break

            event = json.loads(msg)

            key = event["key"]

            with key_lock:
                if event["type"] == "down":
                    pressed_keys.add(key)
                else:
                    pressed_keys.discard(key)

    except Exception as e:
        print("ws error:", e)

    finally:
        conn.close()

        with key_lock:
            pressed_keys.clear()

        print("keyboard disconnected")

def websocket_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, WS_PORT))
    s.listen()

    print(f"WebSocket listening on {WS_PORT}")

    while True:
        conn, addr = s.accept()

        threading.Thread(
            target=websocket_client,
            args=(conn, addr),
            daemon=True
        ).start()

# --------------------------------------------------
# SERIAL
# --------------------------------------------------

def find_responsive_ports():

    responsive = []

    for port_info in serial.tools.list_ports.comports():

        try:
            with serial.Serial(
                port_info.device,
                baudrate=BAUDRATE,
                timeout=0.5
            ) as ser:

                print("Testing", port_info.device)

                ser.write(b"SIGN\0")
                time.sleep(0.2)

                response = ser.read_all()

                if response:
                    print("Response:", response)
                    responsive.append(port_info.device)

        except Exception:
            pass

    return responsive

# --------------------------------------------------
# MOTOR MIXING
# --------------------------------------------------

def get_motor_command():

    speed = 50

    with key_lock:
        keys = set(pressed_keys)

    forward = (
        "w" in keys or
        "W" in keys or
        "ArrowUp" in keys
    )

    backward = (
        "s" in keys or
        "S" in keys or
        "ArrowDown" in keys
    )

    left = (
        "a" in keys or
        "A" in keys or
        "ArrowLeft" in keys
    )

    right = (
        "d" in keys or
        "D" in keys or
        "ArrowRight" in keys
    )

    L = 0
    R = 0

    if forward:
        L += speed
        R += speed

    if backward:
        L -= speed
        R -= speed

    if left:
        L -= speed
        R += speed

    if right:
        L += speed
        R -= speed

    L = max(-127, min(127, L))
    R = max(-127, min(127, R))

    return R, L

# --------------------------------------------------
# CONTROL LOOP
# --------------------------------------------------

def control_loop(port):

    with serial.Serial(
        port,
        baudrate=BAUDRATE,
        timeout=1
    ) as ser:

        print("Connected:", port)

        last_cmd = None

        while True:

            R, L = get_motor_command()

            cmd = f"VR{R}L{L}\0".encode()

            if cmd != last_cmd:
                print(cmd)

            ser.write(cmd)

            last_cmd = cmd

            time.sleep(SEND_PERIOD)

# --------------------------------------------------
# MAIN
# --------------------------------------------------

threading.Thread(
    target=websocket_server,
    daemon=True
).start()

httpd = HTTPServer((HOST, HTTP_PORT), PageHandler)

threading.Thread(
    target=httpd.serve_forever,
    daemon=True
).start()

print(f"http://localhost:{HTTP_PORT}")

ports = find_responsive_ports()

if not ports:
    print("No responsive port found")
    raise SystemExit

control_loop(ports[0])