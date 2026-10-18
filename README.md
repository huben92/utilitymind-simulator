# UtilityMind metering simulator

A local Python standard-library HTTP server and MQTT publisher for synthetic Wheelworks utility readings. The web UI is one page of metering sliders. Changing a slider changes only the current reading; dashboard-owned baseline and maximum values remain unchanged.

## Local setup

Clone this repository as `simulator/` beside the [app](https://github.com/huben92/utilitymind-app) and [API](https://github.com/huben92/utilitymind-api) checkouts, then start the API stack's broker before running:

```bash
python3 app.py --port 8766
```

Open `http://127.0.0.1:8766/`. The publisher starts automatically with broker `127.0.0.1:1884`, topic prefix `factory/wheel-rim`, a 5-second interval, and no TLS. It stores slider state in ignored `data/sensors.sqlite3`. The dashboard's metering catalog is synchronized when the sibling API checkout and its service key are available. Disabled meters appear grayed out.

Override configuration through the process environment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DASHBOARD_URL` | `http://127.0.0.1:8765` | Dashboard catalog endpoint |
| `SIMULATOR_MQTT_HOST` | `127.0.0.1` | Broker hostname |
| `SIMULATOR_MQTT_PORT` | `1884` | Broker port |
| `SIMULATOR_MQTT_TLS` | `0` | Use TLS when `1` |
| `SIMULATOR_MQTT_TOPIC_PREFIX` | `factory/wheel-rim` | MQTT topic prefix |
| `SIMULATOR_INTERVAL` | `5` | Publish interval in seconds |
| `SIMULATOR_PUBLISHING` | `1` | Disable publisher when `0` |
| `SENSOR_DB` | `data/sensors.sqlite3` | Local SQLite cache |
| `SIMULATOR_SERVICE_KEY_FILE` | Sibling `api/data/simulator_service.key` | Shared catalog-sync token |
| `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_CA_CERT` | Empty | Optional external broker authentication |

The page binds to loopback and has no user login; keep it local. This is a simulator, not a real utility control system. Only Python's standard library is required.
