"""Local manufacturing sensor dashboard and MQTT simulator."""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib import error as urlerror, request as urlrequest
import uuid

from mqtt_client import MQTTClient
from sensor_catalog import AREAS, METRICS


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent if (ROOT.parent / "docker-compose.yml").exists() else ROOT
DB_PATH = Path(os.environ.get("SENSOR_DB", PROJECT_ROOT / "data" / "sensors.sqlite3"))
STATIC = ROOT / "static"
LOCK = threading.RLock()
PUBLISH_NOW = threading.Event()
PUBLISH_LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()
SYNC_LAST = 0.0
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8765")
API_ROOT = ROOT.parent / "api" if (ROOT.parent / "api" / "compose.yaml").exists() else PROJECT_ROOT
SIMULATOR_SERVICE_KEY = Path(os.environ.get("SIMULATOR_SERVICE_KEY_FILE", API_ROOT / "data" / "simulator_service.key"))
STATUS = {"state": "stopped", "message": "Publisher has not started", "last_publish": None, "published": 0}


def dashboard_auth_headers():
    try:
        token = SIMULATOR_SERVICE_KEY.read_text().strip()
    except OSError:
        return {}
    return {"Authorization": f"Bearer {token}"} if token else {}


def load_local_env():
    file = PROJECT_ROOT / ".env"
    if not file.exists():
        return
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_CA_CERT"}:
            os.environ.setdefault(key, value)


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def slug(value):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def simulation_ceiling(min_value, max_value):
    """Allow simulated readings beyond the configured operational maximum."""
    return max_value + (max_value - min_value)


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sensors (
                id TEXT PRIMARY KEY, area TEXT NOT NULL, metric TEXT NOT NULL,
                unit TEXT NOT NULL, primary_utility INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1, min_value REAL NOT NULL,
                max_value REAL NOT NULL, baseline REAL NOT NULL, current_value REAL,
                variance REAL NOT NULL DEFAULT 8, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sensor_id TEXT NOT NULL,
                topic TEXT NOT NULL, payload TEXT NOT NULL, published_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dashboard_synced (sensor_id TEXT PRIMARY KEY);
        """)
        if "current_value" not in {row["name"] for row in conn.execute("PRAGMA table_info(sensors)")}:
            conn.execute("ALTER TABLE sensors ADD COLUMN current_value REAL")
        conn.execute("UPDATE sensors SET current_value=baseline WHERE current_value IS NULL")
        defaults = {
            "host": os.getenv("SIMULATOR_MQTT_HOST", "127.0.0.1"),
            "port": os.getenv("SIMULATOR_MQTT_PORT", "1884"),
            "tls": os.getenv("SIMULATOR_MQTT_TLS", "0"),
            "topic_prefix": os.getenv("SIMULATOR_MQTT_TOPIC_PREFIX", "factory/wheel-rim"),
            "interval": os.getenv("SIMULATOR_INTERVAL", "5"),
            "publishing": os.getenv("SIMULATOR_PUBLISHING", "1"),
        }
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (key, value))
        # Explicit environment values take precedence over cached settings.
        for key, env_name in {
            "host": "SIMULATOR_MQTT_HOST",
            "port": "SIMULATOR_MQTT_PORT",
            "tls": "SIMULATOR_MQTT_TLS",
            "topic_prefix": "SIMULATOR_MQTT_TOPIC_PREFIX",
            "interval": "SIMULATOR_INTERVAL",
            "publishing": "SIMULATOR_PUBLISHING",
        }.items():
            if env_name in os.environ:
                conn.execute("UPDATE settings SET value=? WHERE key=?", (os.environ[env_name], key))
        if conn.execute("SELECT COUNT(*) FROM sensors").fetchone()[0] == 0:
            now = datetime.now(timezone.utc).isoformat()
            catalog = AREAS
            for area, metrics in catalog:
                for metric, primary in metrics:
                    config = METRICS[metric]
                    baseline = config["default"]
                    if area in ("Melting Furnace", "Holding Furnace", "Continuous T6 Heat Treatment Furnace Line") and metric == "Electricity":
                        baseline = 210
                    sensor_id = f"{slug(area)}--{slug(metric)}"
                    conn.execute("""INSERT INTO sensors
                        (id,area,metric,unit,primary_utility,active,min_value,max_value,baseline,current_value,variance,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        sensor_id, area, metric, config["unit"], int(primary), 1,
                        config["min"], config["max"], baseline, baseline, 8, now,
                    ))
        removed = "lower(metric) IN ('waste', 'capacity / occupancy')"
        conn.execute(f"DELETE FROM readings WHERE sensor_id IN (SELECT id FROM sensors WHERE {removed})")
        conn.execute(f"DELETE FROM dashboard_synced WHERE sensor_id IN (SELECT id FROM sensors WHERE {removed})")
        conn.execute(f"DELETE FROM sensors WHERE {removed}")


def sync_dashboard_sensors():
    """Copy PostgreSQL sensor metadata into the simulator's local publishing catalog."""
    global SYNC_LAST
    if time.monotonic() - SYNC_LAST < 2 or not SYNC_LOCK.acquire(blocking=False):
        return
    try:
        req = urlrequest.Request(f"{DASHBOARD_URL}/api/simulator-catalog", headers=dashboard_auth_headers())
        with urlrequest.urlopen(req, timeout=2) as response:
            catalog = json.load(response)["sensors"]
        ids = set()
        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            for sensor in catalog:
                if str(sensor["type"]).casefold() in {"waste", "capacity / occupancy"}:
                    continue
                sensor_id = str(sensor["id"])
                ids.add(sensor_id)
                conn.execute("""INSERT INTO sensors
                    (id,area,metric,unit,primary_utility,active,min_value,max_value,baseline,current_value,variance,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                    area=excluded.area,metric=excluded.metric,unit=excluded.unit,
                    active=excluded.active,min_value=excluded.min_value,
                    max_value=excluded.max_value,baseline=excluded.baseline,
                    current_value=min(max(sensors.current_value,excluded.min_value),
                                      excluded.max_value+(excluded.max_value-excluded.min_value))""", (
                    sensor_id, sensor["machine_name"], sensor["type"], sensor["unit"], 0,
                    int(bool(sensor["enabled"])), sensor["min_value"], sensor["max_value"],
                    sensor["baseline"], min(max(sensor["baseline"], sensor["min_value"]), sensor["max_value"]), 8, now,
                ))
                conn.execute("INSERT OR IGNORE INTO dashboard_synced VALUES (?)", (sensor_id,))
            previous = [row[0] for row in conn.execute("SELECT sensor_id FROM dashboard_synced")]
            for sensor_id in previous:
                if sensor_id not in ids:
                    conn.execute("DELETE FROM sensors WHERE id=?", (sensor_id,))
                    conn.execute("DELETE FROM dashboard_synced WHERE sensor_id=?", (sensor_id,))
        SYNC_LAST = time.monotonic()
    except (OSError, ValueError, KeyError, sqlite3.Error):
        pass
    finally:
        SYNC_LOCK.release()


def mirror_dashboard_sensor(sensor_id, updates, conn):
    if not conn.execute("SELECT 1 FROM dashboard_synced WHERE sensor_id=?", (sensor_id,)).fetchone():
        return
    patch = {"id": sensor_id}
    if "active" in updates:
        patch["enabled"] = bool(updates["active"])
    if len(patch) == 1:
        return
    body = json.dumps(patch).encode()
    req = urlrequest.Request(f"{DASHBOARD_URL}/api/master/sensors", body,
                             {"Content-Type": "application/json", **dashboard_auth_headers()}, method="PUT")
    try:
        with urlrequest.urlopen(req, timeout=3):
            pass
    except (OSError, urlerror.HTTPError) as exc:
        raise RuntimeError(f"Could not update dashboard sensor: {exc}") from exc


def settings(conn):
    return {row["key"]: row["value"] for row in conn.execute("SELECT * FROM settings")}


def public_status():
    with LOCK:
        return dict(STATUS)


def mqtt_credentials():
    return os.getenv("MQTT_USERNAME", ""), os.getenv("MQTT_PASSWORD", "")


def publish_batch():
    if not PUBLISH_LOCK.acquire(blocking=False):
        return
    try:
        _publish_batch()
    finally:
        PUBLISH_LOCK.release()


def _publish_batch():
    with db() as conn:
        cfg = settings(conn)
        sensors = [dict(row) for row in conn.execute("SELECT * FROM sensors WHERE active=1 AND lower(metric) NOT IN ('waste', 'capacity / occupancy') ORDER BY area, metric")]
    if not cfg["host"]:
        with LOCK:
            STATUS.update(state="waiting", message="Set a broker host to start publishing")
        return
    username, password = mqtt_credentials()
    client = MQTTClient(cfg["host"], int(cfg["port"]), f"wheel-rim-sim-{uuid.uuid4().hex[:8]}", username, password, cfg["tls"] == "1", os.getenv("MQTT_CA_CERT") or None)
    count = 0
    try:
        client.connect()
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        records = []
        batch_payloads = []
        batch_mode = os.getenv("SIMULATOR_BATCH_MQTT") == "1"
        for sensor in sensors:
            value = round(max(sensor["min_value"], min(simulation_ceiling(sensor["min_value"], sensor["max_value"]), sensor["current_value"])), 2)
            topic = f"{cfg['topic_prefix'].strip('/')}/{slug(sensor['area'])}/{slug(sensor['metric'])}"
            reading = {
                "sensor_id": sensor["id"], "area": sensor["area"], "metric": sensor["metric"],
                "value": value, "unit": sensor["unit"], "timestamp": now,
                "primary": bool(sensor["primary_utility"]), "simulated": True, "quality": "good",
            }
            payload = json.dumps(reading, separators=(",", ":"))
            if batch_mode:
                batch_payloads.append(reading)
            else:
                client.publish(topic, payload)
            records.append((sensor["id"], topic, payload, now))
            count += 1
        if batch_payloads:
            client.publish(f"{cfg['topic_prefix'].strip('/')}/batch",
                           json.dumps({"readings": batch_payloads}, separators=(",", ":")))
        with db() as conn:
            conn.executemany("INSERT INTO readings (sensor_id, topic, payload, published_at) VALUES (?,?,?,?)", records)
            conn.execute("DELETE FROM readings WHERE id NOT IN (SELECT id FROM readings ORDER BY id DESC LIMIT 500)")
        with LOCK:
            STATUS.update(state="connected", message=f"Published {count} readings to {cfg['host']}:{cfg['port']}", last_publish=now, published=STATUS["published"] + count)
    except Exception as exc:
        with LOCK:
            STATUS.update(state="error", message=f"MQTT publish failed: {exc}")
    finally:
        client.close()


def publisher_loop():
    while True:
        started = time.monotonic()
        sync_dashboard_sensors()
        with db() as conn:
            cfg = settings(conn)
        if cfg["publishing"] == "1":
            publish_batch()
        else:
            with LOCK:
                STATUS.update(state="stopped", message="Publisher is paused")
        interval = max(2, min(3600, int(cfg["interval"])))
        PUBLISH_NOW.wait(max(0, interval - (time.monotonic() - started)))
        PUBLISH_NOW.clear()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if not (args and str(args[0]).startswith('GET /api/state ')):
            super().log_message(format, *args)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            raise ValueError("Request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/api/state":
            sync_dashboard_sensors()
            with db() as conn:
                rows = [dict(row) for row in conn.execute("SELECT * FROM sensors ORDER BY rowid")]
                cfg = settings(conn)
                recent = [dict(row) for row in conn.execute("SELECT * FROM readings ORDER BY id DESC LIMIT 10")]
            for row in rows:
                row["simulation_max"] = simulation_ceiling(row["min_value"], row["max_value"])
            for row in recent:
                row["payload"] = json.loads(row["payload"])
            return self.send_json({"sensors": rows, "settings": cfg, "status": public_status(), "recent": recent, "auth_configured": bool(mqtt_credentials()[0])})
        path = "/index.html" if self.path == "/" else self.path
        if path not in ("/index.html", "/styles.css", "/app.js"):
            return self.send_error(404)
        file = STATIC / path.lstrip("/")
        body = file.read_bytes()
        content_type = "text/html" if path.endswith(".html") else "text/css" if path.endswith(".css") else "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            data = self.read_json()
            if self.path == "/api/settings":
                allowed = {"host", "port", "tls", "topic_prefix", "interval", "publishing"}
                updates = {k: str(v).strip() for k, v in data.items() if k in allowed}
                if "host" in updates and (len(updates["host"]) > 253 or not re.fullmatch(r"[A-Za-z0-9.:-]*", updates["host"])):
                    raise ValueError("Invalid broker host")
                if "port" in updates and not 1 <= int(updates["port"]) <= 65535:
                    raise ValueError("Port must be 1–65535")
                if "interval" in updates and not 2 <= int(updates["interval"]) <= 3600:
                    raise ValueError("Interval must be 2–3600 seconds")
                if "topic_prefix" in updates and not re.fullmatch(r"[a-zA-Z0-9/_-]{1,100}", updates["topic_prefix"]):
                    raise ValueError("Invalid topic prefix")
                for key in ("tls", "publishing"):
                    if key in updates and updates[key] not in ("0", "1"):
                        raise ValueError(f"Invalid {key}")
                with db() as conn:
                    conn.executemany("UPDATE settings SET value=? WHERE key=?", [(v, k) for k, v in updates.items()])
                PUBLISH_NOW.set()
                return self.send_json({"ok": True})
            if self.path == "/api/sensors":
                area = str(data.get("area", "")).strip()
                metric = str(data.get("metric", "")).strip()
                if metric.casefold() in {"waste", "capacity / occupancy"}:
                    raise ValueError("This metering category is no longer measured")
                unit = str(data.get("unit", "")).strip()
                low, high = float(data.get("min_value", 0)), float(data.get("max_value", 100))
                baseline = float(data.get("baseline", (low + high) / 2))
                if not area or not metric or not unit or len(area) > 120 or len(metric) > 80 or len(unit) > 20 or not 0 <= low < high <= 1000000 or not low <= baseline <= high:
                    raise ValueError("Check sensor name, unit, and numeric range")
                sensor_id = f"{slug(area)}--{slug(metric)}"
                with db() as conn:
                    conn.execute("""INSERT INTO sensors
                        (id,area,metric,unit,primary_utility,active,min_value,max_value,baseline,current_value,variance,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        sensor_id, area, metric, unit, int(bool(data.get("primary_utility"))), 1,
                        low, high, baseline, baseline, 8, datetime.now(timezone.utc).isoformat(),
                    ))
                return self.send_json({"ok": True, "id": sensor_id}, 201)
            if self.path == "/api/publish-now":
                threading.Thread(target=publish_batch, daemon=True).start()
                return self.send_json({"ok": True})
            return self.send_error(404)
        except (ValueError, sqlite3.IntegrityError) as exc:
            return self.send_json({"error": str(exc)}, 400)

    def do_PATCH(self):
        if not self.path.startswith("/api/sensors/"):
            return self.send_error(404)
        sensor_id = self.path.rsplit("/", 1)[1]
        try:
            data = self.read_json()
            with db() as conn:
                row = conn.execute("SELECT * FROM sensors WHERE id=?", (sensor_id,)).fetchone()
                if not row:
                    return self.send_json({"error": "Metering point not found"}, 404)
                if "baseline" in data or "variance" in data:
                    raise ValueError("Edit baseline in dashboard Metering master data; the simulator controls current readings only.")
                updates = {}
                if "active" in data:
                    updates["active"] = int(bool(data["active"]))
                if "current_value" in data:
                    value = float(data["current_value"])
                    if not math.isfinite(value) or not row["min_value"] <= value <= simulation_ceiling(row["min_value"], row["max_value"]):
                        raise ValueError("Current reading must be within the simulator range")
                    updates["current_value"] = value
                mirror_dashboard_sensor(sensor_id, updates, conn)
                for key, value in updates.items():
                    conn.execute(f"UPDATE sensors SET {key}=? WHERE id=?", (value, sensor_id))
            if updates:
                PUBLISH_NOW.set()
            return self.send_json({"ok": True})
        except (ValueError, RuntimeError) as exc:
            return self.send_json({"error": str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--dashboard-only", action="store_true", help="Serve dashboards without starting another MQTT publisher")
    args = parser.parse_args()
    load_local_env()
    init_db()
    if not args.dashboard_only:
        threading.Thread(target=publisher_loop, daemon=True).start()
    bind_host = os.getenv("SIMULATOR_BIND_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((bind_host, args.port), Handler)
    print(f"Metering simulator: http://{bind_host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
