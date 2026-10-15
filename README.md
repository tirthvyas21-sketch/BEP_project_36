# Smart Object Detection

> **College project** – Detecting restricted-turn traffic violations using computer vision, a FastAPI backend, and an ESP32-S3 Sense camera module.

---

## Architecture Overview

```
┌───────────────────────────────────────────────────────────────┐
│                      System Components                         │
│                                                               │
│  ┌──────────────┐        HTTP/multipart        ┌───────────┐  │
│  │ ESP32-S3     │ ────────────────────────────▶│ FastAPI   │  │
│  │ Sense Camera │  POST /api/detections/analyse│ Backend   │  │
│  │ (firmware/)  │                              │ (main.py) │  │
│  └──────────────┘                              └─────┬─────┘  │
│                                                      │        │
│            ┌─────────────────┬────────────────┐      │        │
│            ▼                 ▼                ▼      │        │
│      ┌──────────┐    ┌──────────────┐  ┌──────────┐ │        │
│      │Detection │    │  OCR Service │  │ SQLite   │◀┘        │
│      │ Service  │    │ (pluggable)  │  │   DB     │          │
│      │(OpenCV)  │    │ Tesseract /  │  │ (data/)  │          │
│      └──────────┘    │Google Vision │  └──────────┘          │
│                      └──────────────┘                         │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  Web Dashboard (/)  –  HTML + CSS + Vanilla JS           │  │
│  │  Interactive table of recent violations + upload form    │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **FastAPI** | Async, auto-generated docs at `/docs`, easy to extend |
| **SQLite → SQLAlchemy** | Zero setup for development; swap to PostgreSQL for production by changing `DATABASE_URL` |
| **Pluggable OCR** | `OcrService.from_config()` reads `OCR_PROVIDER` from `.env` – no code changes to switch backend |
| **Stub-based stubs** | Every unimplemented function logs clearly and returns a safe default so the app runs end-to-end from day one |
| **Firmware separation** | `firmware/` is pure Arduino C++ – no Python tooling leaks in; ESP32 only captures + POSTs |

---

## Project Structure

```
smart-object-detection/
├── main.py                        # FastAPI application entry point
├── requirements.txt
├── .env.example                   # copy to .env – never commit .env
├── .gitignore
├── README.md
├── PROJECT_STATUS.md
│
├── backend/
│   ├── config.py                  # pydantic-settings config
│   ├── database.py                # async SQLAlchemy engine + session
│   ├── models/
│   │   ├── violation.py           # ORM model
│   │   └── schemas.py             # Pydantic request/response schemas
│   ├── routers/
│   │   ├── health.py              # GET /health
│   │   ├── detections.py          # CRUD + POST /api/detections/analyse
│   │   └── dashboard.py           # GET / → renders HTML template
│   ├── services/
│   │   ├── detection_service.py   # OpenCV pipeline (stubs for Phase 2)
│   │   └── ocr_service.py         # pluggable OCR (Tesseract / cloud)
│   ├── templates/
│   │   └── dashboard.html         # Jinja2 HTML template
│   └── static/
│       ├── css/style.css
│       └── js/dashboard.js
│
├── firmware/
│   └── main.ino                   # ESP32-S3 Arduino firmware
│
├── tests/
│   ├── test_health.py
│   └── test_detections.py
│
├── sample_images/                 # safe demo images only – no real plates
└── data/                          # SQLite database (gitignored)
```

---

## Quick Start

### 1 – Clone and set up environment

```bash
# Windows (PowerShell)
cd smart-object-detection
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2 – Configure environment

```bash
copy .env.example .env      # Windows
cp  .env.example .env       # macOS/Linux
# Edit .env with your settings (leave defaults for development)
```

### 3 – Run the server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** – you'll see the dashboard.  
Open **http://localhost:8000/docs** – interactive API explorer.

### 4 – Run tests

```bash
pytest tests/ -v
```

---

## ESP32-S3 Firmware

See [`firmware/main.ino`](firmware/main.ino).

**Arduino IDE setup:**
1. Board Manager → install `esp32` by Espressif (≥ 3.x)
2. Select board: *XIAO_ESP32S3*
3. Library Manager → install `ArduinoJson` (≥ 7.x)
4. Edit `WIFI_SSID`, `WIFI_PASSWORD`, `API_HOST` constants
5. Upload

> **Note:** Camera capture and HTTP POST are stubs in Phase 1. Connect the backend first; add camera code in Phase 2.

---

## Swapping the OCR Backend

Edit `.env`:

```
OCR_PROVIDER=local        # uses _LocalOcrService (Tesseract / EasyOCR)
OCR_PROVIDER=google_vision
OCR_PROVIDER=azure
```

Then implement the corresponding `_*OcrService.read_plate()` method in [`backend/services/ocr_service.py`](backend/services/ocr_service.py). No other file needs to change.

---

## Data & Privacy

- **Never commit** real vehicle images, real plate numbers, or student data to this repository.
- `data/` (SQLite database) is gitignored.
- `sample_images/real/` is gitignored.
- Use synthetic/blurred images for demos.

---

## Roadmap

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for phase tracking.
