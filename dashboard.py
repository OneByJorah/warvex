#!/usr/bin/env python3
"""warvex Dashboard — lightweight Flask dashboard for WARP gateway status."""
import os, json, subprocess, time
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import threading

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins=[], async_mode="eventlet")
PORT = int(os.environ.get("DASHBOARD_PORT", 8080))
AP_SUBNET = os.environ.get("AP_SUBNET", "192.168.50.0/24")
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() in ("1", "true", "yes")

# Demo data for screenshots and local previews. Documentation-range IPs
# (TEST-NET-3, RFC 5737) and locally administered MACs — never real hosts.
DEMO_STATS = {
    "warp": "Connected",
    "warp_ip": "203.0.113.7",
    "uptime": "2d 04:12 (demo data)",
    "clients": 3,
    "cpu": 23,
    "mem_pct": 41,
    "temp": 47,
    "rx_kbps": 1840,
    "tx_kbps": 612,
    "rx_today": "1.4 GB",
    "tx_today": "386 MB",
    "note": "Demo data (DEMO_MODE=true)",
}

DEMO_LEASES = [
    {"ip": "203.0.113.10", "mac": "02:00:00:00:00:01", "name": "demo-laptop", "expires": "0"},
    {"ip": "203.0.113.11", "mac": "02:00:00:00:00:02", "name": "demo-phone", "expires": "0"},
    {"ip": "203.0.113.12", "mac": "02:00:00:00:00:03", "name": "demo-tv", "expires": "0"},
]

def get_stats():
    if DEMO_MODE:
        return DEMO_STATS
    try:
        r = subprocess.run(["/usr/local/bin/gw-stats.sh"], capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout)
    except Exception as e:
        # Mock stats for container-only / local dev when Pi hardware/WARP is absent
        return {
            "warp": "Disconnected",
            "warp_ip": "N/A",
            "uptime": "0m (preview mode)",
            "clients": 0,
            "cpu": 12,
            "mem_pct": 34,
            "temp": 42,
            "rx_kbps": 0,
            "tx_kbps": 0,
            "rx_today": "0 MB",
            "tx_today": "0 MB",
            "note": "Running in dashboard-only preview mode",
        }

def get_leases():
    if DEMO_MODE:
        return DEMO_LEASES
    leases = []
    try:
        with open("/var/lib/misc/dnsmasq.leases") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 4:
                    leases.append({"ip": parts[2], "mac": parts[1], "name": parts[3], "expires": parts[0]})
    except:
        pass
    return leases

@app.before_request
def restrict_subnet():
    if request.method == "POST":
        client_ip = request.remote_addr
        if client_ip in ("127.0.0.1", "::1"):
            return None
        if not client_ip.startswith(AP_SUBNET.rsplit(".", 1)[0] + "."):
            return jsonify({"error": "Forbidden: not on AP subnet"}), 403

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

@app.route("/api/clients")
def api_clients():
    return jsonify(get_leases())

@app.route("/api/warp/toggle", methods=["POST"])
def warp_toggle():
    stats = get_stats()
    if stats.get("warp") == "Connected":
        subprocess.run(["warp-cli", "disconnect"])
        return jsonify({"action": "disconnected"})
    else:
        subprocess.run(["warp-cli", "connect"])
        return jsonify({"action": "connected"})

@app.route("/api/warp/reconnect", methods=["POST"])
def warp_reconnect():
    subprocess.run(["warp-cli", "disconnect"])
    time.sleep(2)
    subprocess.run(["warp-cli", "connect"])
    return jsonify({"action": "reconnected"})

@app.route("/api/restart/<service>", methods=["POST"])
def restart_service(service):
    allowed = ["hostapd", "dnsmasq", "warp-svc"]
    if service not in allowed:
        return jsonify({"error": "not allowed"}), 403
    subprocess.run(["systemctl", "restart", service])
    return jsonify({"action": f"restarted {service}"})

@app.route("/api/reboot", methods=["POST"])
def reboot_pi():
    subprocess.Popen(["bash", "-c", "sleep 3 && reboot"])
    return jsonify({"action": "rebooting in 3 seconds"})

def push_stats():
    while True:
        socketio.emit("stats", get_stats())
        time.sleep(3)

@socketio.on("connect")
def on_connect():
    pass

def main():
    t = threading.Thread(target=push_stats, daemon=True)
    t.start()
    socketio.run(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
