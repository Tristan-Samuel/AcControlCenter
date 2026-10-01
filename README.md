# AC Control Center

School-wide air-conditioning policy: a **central Raspberry Pi** on the school LAN runs the web app. Each classroom has an **ESP32** that reports door/temperature state and fires IR commands. Policy (auto-shutoff, buzzer, allow/deny remote ON) lives on the server.

## Architecture

```
Classroom ESP32  -- HTTP + MAC + X-API-Key -->  gunicorn on central Pi :5000
Teacher on campus ----------------------------->  http://<pi-lan-ip>:5000
Admin off campus  -> https://ac.school.edu  -- reverse proxy -->  same Pi
```

- **Server:** Flask + SQLite (WAL) + APScheduler, one gunicorn worker so jobs are not duplicated.
- **Classroom node:** `[firmware/ac_node](firmware/ac_node)` heartbeats to `POST /api/v1/heartbeat` and runs queued commands (`POWER_OFF`, `POWER_ON` + `SET_TEMP_`*).
- Devices identify by **Wi-Fi MAC**. Room number is the human label in the UI.
- Temperatures are stored in **Celsius** and displayed in **Fahrenheit**.
- ESP32s must always use `SERVER_URL=http://<central-pi-lan-ip>:5000`. An internet outage should not take down in-building control.

A DNS/HTTP **redirect** from a school subdomain to `10.x.x.x` only works on campus. Off-campus access needs a **reverse proxy** (preferred) or optional ngrok.

## Security model

The previous Replit build exposed device APIs on a public ngrok URL with no auth, allowed anyone to register as admin, and treated a failed password hash as a successful login. This tree does the opposite:


| Control    | Behavior                                                                                                          |
| ---------- | ----------------------------------------------------------------------------------------------------------------- |
| Device API | Every `/api/v1/*` call except enroll needs `X-API-Key` for that room. Keys are hashed at rest and shown **once**. |
| Identity   | MAC is hardware identity (spoofable). The API key is the secret.                                                  |
| Admins     | Created with `python -m ac_control.cli create-admin`. Public registration never grants admin.                     |
| Sessions   | `SESSION_SECRET` required in production. HTTPS cookies when `PREFERRED_URL_SCHEME=https`.                         |
| CSRF       | Flask-WTF on browser forms. Device blueprint is CSRF-exempt (API key instead).                                    |
| Login      | Rate-limited. Password/PIN checks never rewrite hashes on failure.                                                |
| Secrets    | Only in `/etc/ac-control.env`. Never commit `.env`.                                                               |


**Rotate the ngrok token that was hardcoded in the old** `main.py` **and the public GitHub history.** Treat it as burned: [ngrok dashboard](https://dashboard.ngrok.com/) → revoke, issue a new token, put it only in `/etc/ac-control.env` if you still use ngrok.

This repo should be **private**. It describes how a school building is controlled, and old commits still contain the leaked token until you rotate it and/or change visibility.

## Central Pi install

On Raspberry Pi OS (64-bit, Python 3.11+):

```bash
sudo useradd --system --home /opt/ac-control --shell /usr/sbin/nologin accontrol
sudo mkdir -p /opt/ac-control /var/lib/ac-control
sudo chown accontrol:accontrol /opt/ac-control /var/lib/ac-control

sudo -u accontrol git clone https://github.com/Tristan-Samuel/AcControlCenter.git /opt/ac-control
cd /opt/ac-control
sudo -u accontrol python3 -m venv .venv
sudo -u accontrol .venv/bin/pip install -e .

sudo cp .env.example /etc/ac-control.env
sudo chmod 600 /etc/ac-control.env
# Edit SESSION_SECRET (required). Give the Pi a DHCP reservation.

sudo cp deploy/school.service /etc/systemd/system/ac-control.service
sudo systemctl daemon-reload
sudo systemctl enable --now ac-control.service
```

Create the first admin (does not go through the web):

```bash
cd /opt/ac-control
sudo -u accontrol FLASK_ENV=production SESSION_SECRET=... \
  .venv/bin/python -m ac_control.cli create-admin \
  --username admin --email you@school.edu
```

Create a classroom:

```bash
sudo -u accontrol FLASK_ENV=production SESSION_SECRET=... \
  .venv/bin/python -m ac_control.cli create-room \
  --room 7 --username room7 --email facilities@school.edu
```

Bind an ESP32 after it appears under **Users → Unassigned ESP32s**, or:

```bash
sudo -u accontrol FLASK_ENV=production SESSION_SECRET=... \
  .venv/bin/python -m ac_control.cli bind-mac \
  --room 7 --mac AA:BB:CC:DD:EE:FF
```

Health check: `curl -s http://127.0.0.1:5000/health`

### Off-campus admin access

ESP32s stay on the LAN. Browsers off campus need one of:

1. **Preferred:** school IT reverse-proxies a subdomain to the Pi. Example nginx on the school web server:

```nginx
server {
    listen 443 ssl;
    server_name ac.yourschool.edu;
    # ssl_certificate / ssl_certificate_key from the school's certs

    location / {
        proxy_pass http://10.0.0.5:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then in `/etc/ac-control.env`:

```
PUBLIC_BASE_URL=https://ac.yourschool.edu
PREFERRED_URL_SCHEME=https
```

1. **Fallback:** reserved ngrok domain (`USE_NGROK=true`) if IT cannot proxy.
2. Firewall port-forward (worse).

Do not point ESP32 `SERVER_URL` at the public hostname.

### Ngrok (optional)

1. Reserve a **static domain** at ngrok.
2. In `/etc/ac-control.env`:

```
USE_NGROK=true
NGROK_AUTHTOKEN=...
NGROK_DOMAIN=your-name.ngrok-free.app
PREFERRED_URL_SCHEME=https
```



## Classroom ESP32

Same firmware on every board (`[firmware/ac_node](firmware/ac_node)`).

### Flash

Arduino IDE or `arduino-cli`, board **ESP32 Dev Module**. Libraries: **IRremoteESP8266**, **ArduinoJson**, **WiFiManager**. Copy `[firmware/ac_node/config.h.example](firmware/ac_node/config.h.example)` to `config.h` if you want compiled-in Wi-Fi; otherwise leave SSID blank and use the captive portal.

On first boot the board opens Wi-Fi AP `AC-Node-XXXX`. Enter school Wi-Fi, `SERVER_URL=http://<pi-lan-ip>:5000`, and optional enroll token / API key.

### Identity

The board POSTs `POST /api/v1/enroll` with its STA MAC. It stays **pending** until an admin assigns that MAC to a room. The next enroll poll returns `api_key` **once**; it is stored in NVS.

Manual path: paste a room API key in WiFiManager. The first heartbeat with `room_number` + key binds the MAC.

### Wiring


| Piece                             | Typical GPIO | Notes                                                                           |
| --------------------------------- | ------------ | ------------------------------------------------------------------------------- |
| IR transmitter (LED + transistor) | 4            | `IRsend`; fill `[ir_profile.h](firmware/ac_node/ir_profile.h)` after learn mode |
| IR receiver (e.g. VS1838B)        | 15           | Physical remote ON is reported to the server; setpoint comes from the server    |
| Door reed switch                  | 16, pull-up  | Low = closed, high = open                                                       |
| Active buzzer                     | 18           | Server sets `buzz: true` while the door is open if enabled                      |
| DHT22 (optional)                  | 17           | Ambient only; `#define USE_DHT 1`                                               |
| Extra window reeds                | 19+          | Wired for a later upgrade; policy ignores `window_state` for now                |


Hold **BOOT** (GPIO 0) for 3 seconds at reset to dump IR captures on serial at 115200 baud. Paste timings into `ir_profile.h`.

If the server is unreachable, the node **fails closed** (does not honor a local ON).

### Simulation mode (no hardware)

Set `SIMULATION_MODE=true` and the server itself pretends to be four classroom nodes. Heartbeats go through `process_heartbeat`, so door shutoff, the buzzer, temperature lockout, and remote allow/deny are the real policy code. The admin dashboard has buttons (open door, remote ON, node offline) and a line that says what the Pi just queued.

On the home Pi this is the default install. See `vps-stack` `PI.md` section 22. Log in as `demo`. The password is the `password:` line in `simulation-login.txt` next to the database (`/var/lib/ac-control/simulation-login.txt` on the Pi). The app reads that file when you sign in, so editing the line changes the login.

```bash
export SIMULATION_MODE=true
export SIMULATION_ADMIN_PASSWORD=adminadmin
flask --app wsgi run --port 5000
```

`[pi_client/ac_client.py](pi_client/ac_client.py)` is the older single-node HTTP client, if you want a process outside the server:

```bash
SERVER_URL=http://127.0.0.1:5000 DEVICE_MAC=02:00:00:00:00:07 \
  DEVICE_API_KEY=... SIMULATE=1 python pi_client/ac_client.py
```



## How policy works

- **Setpoint:** last temperature the IR blaster should send. A remote that only means “ON” turns the unit on to this value, not a factory default. Change it on the room dashboard.
- **Door open:** `auto_shutoff` queues `POWER_OFF` after `shutoff_delay`. `buzz_on_open` sets `buzz: true` on each heartbeat until the door closes. Both can be enabled.
- **Windows:** `window_state` is stored for a later reed-switch upgrade and does **not** shut off the AC yet.
- Scheduled night shutoff and temperature floors are unchanged.



## Environment variables

See `[.env.example](.env.example)`. Important:

- `FLASK_ENV=production` — refuses to start without `SESSION_SECRET`
- `ALLOW_PUBLIC_REGISTRATION=false` (default) — teachers should not self-provision
- `STALE_AFTER_SECONDS=180` — dashboard marks rooms whose ESP32 has not checked in
- `ENROLL_TOKEN` — optional shared secret for `/api/v1/enroll`
- `PUBLIC_BASE_URL` — reverse-proxied dashboard URL (browsers only)



## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export SESSION_SECRET=dev-only-not-for-production
export FLASK_ENV=development
flask --app wsgi run --port 5000
```

In another terminal:

```bash
python -m ac_control.cli create-admin --username admin --email admin@localhost --password adminadmin
python -m ac_control.cli create-room --room 7 --username room7 --email room7@localhost --password room7room7
SERVER_URL=http://127.0.0.1:5000 ROOM_NUMBER=7 DEVICE_API_KEY=... SIMULATE=1 python pi_client/ac_client.py
```

```bash
pytest
```

Gunicorn locally (same as the Pi):

```bash
gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 8 wsgi:app
```



## HTTP surface


| Path                         | Auth                    | Purpose                                                                 |
| ---------------------------- | ----------------------- | ----------------------------------------------------------------------- |
| `/` `/login` `/logout`       | session                 | Web login (password or PIN)                                             |
| `/admin/*`                   | admin session           | Rooms, policy, users, event CSV, assign ESP32 MAC                       |
| `/room` `/settings/...`      | room or admin           | Dashboard and settings                                                  |
| `POST /api/v1/enroll`        | optional `ENROLL_TOKEN` | ESP32 MAC registration / key pickup                                     |
| `POST /api/v1/heartbeat`     | `X-API-Key`             | Ingest door/IR state; return IR commands + `buzz` + `set_temperature_c` |
| `POST /api/v1/check-command` | `X-API-Key`             | Allow/deny a physical remote press                                      |
| `GET /health`                | none                    | `{ok, public_url, ngrok}` no secrets                                    |


