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

## 3. Software install

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-venv git libgl1
# Check the camera works:
rpicam-hello -t 2000

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
TRAP_ID=T1-polyhouse            # must exist in config/traps.yaml
BACKEND_URL=http://<laptop-ip>:8000
LED_PIN=23
```

Copy the trained `best.pt` to `ml/weights/best.pt` on the Pi so detection runs on
the device. On a Pi 4, SAHI inference on a full 12 MP photo takes a while
(about a minute is normal; it runs once a day). If it is too slow, set
`LOCAL_DETECTION=0` and the backend will detect instead.

## 4. Calibrate the tape advance

`STEPS_PER_SECTION` = half-steps needed to pull exactly one camera-frame of fresh tape.

```bash
python -c "from edge.hardware.stepper import Stepper; Stepper([17,18,27,22], 0, mock=False).step(1000)"
```

Measure how many millimetres the tape moved for 1000 half-steps, then:
`STEPS_PER_SECTION = 1000 × (section length in mm) / (mm moved)`.
Note: as the take-up spool fills, each turn pulls slightly more tape; recalibrate
when a roll is half used, or leave a small gap between sections.

## 5. Test one cycle

```bash
python -m edge.main --once
```

You should see: stepper advancing → photo saved in `edge/data/images/` →
local detection counts → climate reading → "Synced section" (or "kept offline").

## 6. Run as a systemd service (starts at boot, restarts on crash)

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

## 7. Offline behaviour

Every photo and reading is first saved in `edge/data/queue.db`. If the laptop or
network is down, items stay there and are retried with growing waits (10 s, 20 s,
40 s … max 10 min). Nothing is lost when the power comes back: the queue is on the SD card.
