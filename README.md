# AC Control Center

School-wide air-conditioning policy for classrooms: a **central Raspberry Pi** runs the web app, and each classroom Pi reports window/temperature state and executes IR commands. Optional **ngrok** (reserved domain) lets classroom Pis on other VLANs or off-campus reach the server.

## Architecture

```
Classroom Pi  -- HTTPS + X-API-Key -->  ngrok static domain  -->  gunicorn on central Pi
Teacher browser ----------------------->  same URL or LAN IP:5000
```

- **Server:** Flask + SQLite (WAL) + APScheduler, one gunicorn worker so jobs are not duplicated.
- **Classroom agent:** [`pi_client/ac_client.py`](pi_client/ac_client.py) heartbeats to `POST /api/v1/heartbeat` and runs queued commands (`POWER_OFF`, `POWER_ON`, `SET_TEMP_*`).
- Temperatures are stored in **Celsius** and displayed in **Fahrenheit**.

If classroom Pis can reach the central Pi on the LAN, set `SERVER_URL=http://<central-pi-ip>:5000` and skip ngrok. An internet outage should not take down in-building control.

## Security model

The previous Replit build exposed device APIs on a public ngrok URL with no auth, allowed anyone to register as admin, and treated a failed password hash as a successful login. This tree does the opposite:

| Control | Behavior |
| --- | --- |
| Device API | Every `/api/v1/*` call needs `X-API-Key` for that room. Keys are hashed at rest and shown **once**. |
| Admins | Created with `python -m ac_control.cli create-admin`. Public registration never grants admin. |
| Sessions | `SESSION_SECRET` required in production. HTTPS cookies when ngrok/`PREFERRED_URL_SCHEME=https`. |
| CSRF | Flask-WTF on browser forms. Device blueprint is CSRF-exempt (API key instead). |
| Login | Rate-limited. Password/PIN checks never rewrite hashes on failure. |
| Secrets | Only in `/etc/ac-control.env` / `/etc/ac-client.env`. Never commit `.env`. |

**Rotate the ngrok token that was hardcoded in the old `main.py` and the public GitHub history.** Treat it as burned: [ngrok dashboard](https://dashboard.ngrok.com/) → revoke, issue a new token, put it only in `/etc/ac-control.env`.

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
# Edit SESSION_SECRET (required), mail, ngrok.
# python3 -c "import secrets; print(secrets.token_hex(32))"

sudo cp deploy/ac-control.service /etc/systemd/system/
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

Create a classroom and print a device key:

```bash
sudo -u accontrol FLASK_ENV=production SESSION_SECRET=... \
  .venv/bin/python -m ac_control.cli create-room \
  --room 7 --username room7 --email facilities@school.edu
```

You can also create rooms in the web UI under **Users** after logging in as admin.

Health check: `curl -s http://127.0.0.1:5000/health`

### Ngrok (cross-VLAN / off-campus)

1. Reserve a **static domain** at ngrok (free tier includes one).
2. In `/etc/ac-control.env`:

```
USE_NGROK=true
NGROK_AUTHTOKEN=...
NGROK_DOMAIN=your-name.ngrok-free.app
PREFERRED_URL_SCHEME=https
```

3. Put that HTTPS URL in each classroom `SERVER_URL`. Do not try to discover the tunnel from `localhost` — classroom Pis cannot see the central Pi’s loopback.

## Classroom Pi install

```bash
sudo mkdir -p /opt/ac-client
sudo cp pi_client/ac_client.py /opt/ac-client/
sudo cp pi_client/config.example.env /etc/ac-client.env
sudo chmod 600 /etc/ac-client.env
# Set SERVER_URL, ROOM_NUMBER, DEVICE_API_KEY
# SIMULATE=1 until GPIO/IR are wired

sudo apt-get install -y python3-requests
# For hardware later: python3-rpi.gpio / lirc as needed

sudo cp deploy/ac-client.service /etc/systemd/system/
sudo systemctl enable --now ac-client.service
```

Bring-up without hardware: `SIMULATE=1`. The agent still heartbeats and will execute queued IR stubs.

### Hardware (optional)

| Piece | Typical wiring | Notes |
| --- | --- | --- |
| Magnetic reed switch | GPIO 17, pull-up | Low = closed, high = open (matches the client) |
| IR LED + transistor | LIRC / `irsend` | Learn codes with `irrecord`; replace the stub in `send_ir_command` |
| DHT22 | GPIO 4 | Optional; simulation is used until you add a driver |

## Environment variables

See [`.env.example`](.env.example). Important:

- `FLASK_ENV=production` — refuses to start without `SESSION_SECRET`
- `ALLOW_PUBLIC_REGISTRATION=false` (default) — teachers should not self-provision
- `STALE_AFTER_SECONDS=180` — dashboard marks rooms whose Pi has not checked in

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

| Path | Auth | Purpose |
| --- | --- | --- |
| `/` `/login` `/logout` | session | Web login (password or PIN) |
| `/admin/*` | admin session | Rooms, policy, users, event CSV |
| `/room` `/settings/...` | room or admin | Dashboard and settings |
| `POST /api/v1/heartbeat` | `X-API-Key` | Ingest state; return IR commands |
| `POST /api/v1/check-command` | `X-API-Key` | Allow/deny a remote button press |
| `GET /health` | none | `{ok, ngrok}` no secrets |

## Backlog

- Real LIRC profiles per AC brand/model
- DHT22 (or I²C sensor) instead of simulated temperature
- Tailscale as an ngrok alternative on the school network
- PostgreSQL if you outgrow SQLite
- Audit-log export beyond CSV; per-teacher roles (not only admin vs room)
- Hardware watchdog / dead-man IR off if the server is unreachable for too long

## License

Use and modify for your school. No warranty: IR control of HVAC can waste energy or stress equipment if policy or wiring is wrong. Test in simulate mode first.
