
"""
python demo-webserver-keyboard.py

192.168.1.228:8080
"""

import base64
import hashlib
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "0.0.0.0"
HTTP_PORT = 8080
WS_PORT = 8765

HTML = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Key Capture</title>
</head>
<body>
<h1>Keyboard Event Sender</h1>

<script>
const ws = new WebSocket("ws://" + location.hostname + ":{WS_PORT}");

document.addEventListener("keydown", (e) => {{
    ws.send(JSON.stringify({{
        type: "down",
        key: e.key,
        code: e.code
    }}));
}});

document.addEventListener("keyup", (e) => {{
    ws.send(JSON.stringify({{
        type: "up",
        key: e.key,
        code: e.code
    }}));
}});
</script>

</body>
</html>
"""


# ---------------- HTTP SERVER ----------------

class PageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def log_message(self, *args):
        pass


# ---------------- WEBSOCKET ----------------

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def websocket_handshake(conn):
    data = conn.recv(4096).decode()

    key = None
    for line in data.split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
            break

    if not key:
        conn.close()
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

    return payload.decode("utf-8")


def websocket_client(conn, addr):
    try:
        if not websocket_handshake(conn):
            return

        print("connected:", addr)

        while True:
            msg = read_ws_frame(conn)
            if msg is None:
                break

            event = json.loads(msg)

            print(
                f"{event['type']:4} "
                f"key={event['key']!r} "
                f"code={event['code']}"
            )

    except Exception as e:
        print("client error:", e)

    finally:
        conn.close()
        print("disconnected:", addr)


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


# ---------------- MAIN ----------------

threading.Thread(target=websocket_server, daemon=True).start()

httpd = HTTPServer((HOST, HTTP_PORT), PageHandler)

print(f"HTTP server: http://localhost:{HTTP_PORT}")
httpd.serve_forever()