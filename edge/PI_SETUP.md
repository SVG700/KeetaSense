# Raspberry Pi setup guide

This guide turns a Raspberry Pi (4 or 5, 64-bit Raspberry Pi OS Bookworm) into a
KeetaSense trap controller.

## 1. Parts

| Part | Notes |
|---|---|
| Raspberry Pi 4 (2 GB+) or Pi 5 | 64-bit Raspberry Pi OS (Bookworm) |
| Raspberry Pi Camera Module 3 (or HQ camera) | ribbon cable to the CSI/CAM port |
| 28BYJ-48 5 V stepper motor + ULN2003 driver board | turns the tape take-up spool |
| DHT22 (AM2302) sensor | 10 kΩ pull-up resistor if your board has none |
| White LED strip/ring (5 V or 12 V) + logic-level MOSFET (e.g. IRLZ44N) or a relay module | lights the dark chamber |
| 5 V 3 A supply (Pi 5: 5 V 5 A) | motor can share it; better: separate 5 V for the motor with common ground |

## 2. Wiring

GPIO numbers are **BCM** numbers (what the code uses). "Pin" is the physical
pin number on the 40-pin header.

### ULN2003 stepper driver

| ULN2003 pin | Raspberry Pi | Physical pin | .env setting |
|---|---|---|---|
| IN1 | GPIO17 | 11 | `STEPPER_PINS=17,18,27,22` (1st) |
| IN2 | GPIO18 | 12 | (2nd) |
| IN3 | GPIO27 | 13 | (3rd) |
| IN4 | GPIO22 | 15 | (4th) |
| + (5-12 V) | 5 V | 2 or 4 | |
| − (GND) | GND | 6 | |

Plug the motor's white 5-pin connector into the ULN2003 board.

### DHT22

| DHT22 pin | Raspberry Pi | Physical pin | .env setting |
|---|---|---|---|
| VCC (+) | 3.3 V | 1 | |
| DATA | GPIO4 | 7 | `DHT22_PIN=4` |
| GND (−) | GND | 9 | |

Put a 10 kΩ resistor between DATA and 3.3 V if you use the bare 4-pin sensor
(the 3-pin modules already have it). Mount the sensor **outside** the dark
chamber, in the shade, so the LEDs do not heat it.

### LED lighting (optional, recommended)

| Part | Raspberry Pi | Physical pin | .env setting |
|---|---|---|---|
| MOSFET gate (via 220 Ω) or relay IN | GPIO23 | 16 | `LED_PIN=23` |
| MOSFET source / relay GND | GND | 14 | |

Never power LEDs directly from a GPIO pin.

## 3. Bring-up order (do these in order; each step has its own PASS/FAIL tool)

Every test prints **PASS / WARN / FAIL** with troubleshooting hints, and exits with
code 1 on FAIL. Fix a FAIL before going to the next step.

### Step 0 - OS and software

Raspberry Pi OS (64-bit, Bookworm) with SSH enabled (Raspberry Pi Imager → settings: hostname,
user, Wi-Fi, SSH). Then on the Pi:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-picamera2 python3-venv git libgl1
rpicam-hello --list-cameras          # the camera must be listed

# Get the project onto the Pi (git clone or copy the folder), then:
cd keetasense
python3 -m venv --system-site-packages .venv     # system packages = picamera2
source .venv/bin/activate
pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
pip install -r edge/requirements-pi.txt
cp .env.example .env
nano .env
```

In `.env` on the Pi set at least:

```
MOCK_HARDWARE=0
TRAP_ID=T1-polyhouse            # must exist in config/traps.yaml on the laptop
BACKEND_URL=http://<laptop-ip>:8000
LED_PIN=23
```

### Step 1 - camera

```bash
python -m edge.tests_hw.test_camera --real --out edge/data/hw_test/cam.jpg
```
Checks: an image is captured, resolution, brightness (40-225), sharpness. Open the saved
photo (e.g. `scp` it to the laptop) and check the tape fills the frame and is evenly lit.

### Step 2 - DHT22

```bash
python -m edge.tests_hw.test_dht22 --real --reads 5
```
Checks: success rate of 5 reads (PASS at ≥ 60 %) and plausible values.

### Step 3 - stepper motor

```bash
python -m edge.tests_hw.test_stepper --real --steps 512 --direction both
python -m edge.tests_hw.test_stepper --real --steps 4096 --direction forward --delay 0.002   # one full turn
```
Watch the shaft (stick a piece of tape on it) and the four LEDs on the ULN2003 board.

### Step 4 - tape calibration (`STEPS_PER_SECTION`)

Load the tape roll, draw a pen line on the tape at the top edge of the camera view, then:

```bash
python -m edge.calibrate_tape --real
```
Press **Enter** to advance by the step size (default 256 half-steps; type a number to change
it, `b` to go back). After every step a photo with a red reference line is saved in
`edge/data/calibration/`. When the pen line has just left the camera view, press **s**: the
total is written to `.env` as `STEPS_PER_SECTION` (old file kept as `.env.bak`).
As the take-up spool fills, each turn pulls slightly more tape - recalibrate when a roll is
half used, or leave a small gap between sections.

### Step 5 - backend link

On the laptop start the backend so the Pi can reach it: `scripts\start.bat --lan`
(or `bash scripts/start.sh --lan`). Then on the Pi:

```bash
python -m edge.tests_hw.test_backend_link
```
Checks: `/api/health` reachable (latency), `TRAP_ID` known by the backend, a test reading is
accepted (dry run - nothing is stored).

### Step 6 - full run with mock hardware OFF

```bash
python -m edge.main --once          # one complete cycle, starts with the self-check table
python -m edge.main --demo          # one cycle every 20 s - watch the dashboard (Live on)
```
You should see the self-check table, then: stepper advancing → photo saved in
`edge/data/images/` → local detection counts → climate reading → "Synced section".
Note how long the "Local detection" step takes in the log timestamps: SAHI on a full
12 MP photo can be slow on a Pi 4. If it is too slow for the demo, set `LOCAL_DETECTION=0`
and the laptop backend detects instead.

Copy the trained model to the Pi as well (`python -m ml.install_model <zip>` on the Pi) so the
detection on the device uses the AI model; without it the Pi uses the demo detector.

### Step 7 - make a replay pack (stage insurance)

Every cycle is recorded in `edge/data/recording/<TRAP_ID>/`. After a good rehearsal run with
real tape, turn it into a replay pack and copy it to the laptop:

```bash
python -m edge.replay edge/data/recording/T1-polyhouse demo/replay_real --note "rehearsal 3 Nov"
```
If the camera or Pi fails on stage, run on the laptop:
`python -m edge.main --demo --replay demo/replay_real` - the dashboard labels it **Replay**.

### Startup self-check

`python -m edge.main` always starts with a quick check of camera, DHT22, stepper (no
movement), backend link and detector, and prints a table. Problems are reported but the
service still starts (data waits in the offline queue). Skip it with `--skip-selfcheck`.

## 4. Run as a systemd service (starts at boot, restarts on crash)

Create `/etc/systemd/system/keetasense-edge.service` (adjust user and path):

```ini
[Unit]
Description=KeetaSense edge service (sticky trap controller)
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/keetasense
ExecStart=/home/pi/keetasense/.venv/bin/python -m edge.main
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now keetasense-edge
journalctl -u keetasense-edge -f      # watch the log
```

## 5. Offline behaviour

Every photo and reading is first saved in `edge/data/queue.db`. If the laptop or
network is down, items stay there and are retried with growing waits (10 s, 20 s,
40 s … max 10 min). Nothing is lost when the power comes back: the queue is on the SD card.
