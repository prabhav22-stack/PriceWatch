# PriceWatch 2.1 🎯⚡

[![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.15-blue.svg)](https://www.python.org/)
[![Tests Passing](https://img.shields.io/badge/tests-162%20passed-brightgreen.svg)](tests/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-@wheypricewatch__bot-blue?logo=telegram)](https://t.me/wheypricewatch_bot)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> An enterprise-grade, multi-store price intelligence platform and Telegram assistant tailored for Indian fitness nutrition and e-commerce.

PriceWatch continuously monitors prices, warehouse inventory, and deals across **Amazon.in, Flipkart, HyugaLife, HealthKart, MuscleBlaze, Amul Shop, Nutrabay, Nakpro, and AS-IT-IS Nutrition**, alerting users instantly via Telegram, Discord, NTFY, or Slack.

---

## 🌟 Key Features

### 🔍 1. Cross-Store Price & Stock Comparison (`/compare`)
- **Parallel Multi-Store Search**: Concurrently queries 7+ trusted fitness platforms.
- **Brand & Weight Normalization**: Powered by `rapidfuzz` and metric parsers (`kg`, `g`, `lbs`, `tabs`), guaranteeing zero false positives across competitor brands.
- **Best Deal Highlighter**: Badges the cheapest in-stock seller and computes exact rupee savings.

### ⚡ 2. Proactive Out-of-Stock Finder & 1-Click Switch Tracking
- If a product you track is Out of Stock (e.g. *Nutrabay Pure Shilajit*), PriceWatch scans alternative stores in the background.
- If found in stock elsewhere (e.g. *Flipkart*), you immediately receive a proactive alert with an inline **`[ ⚡ Switch Tracking to <Store> ]`** button to migrate your monitoring subscription in 1 tap.

### 🏷️ 3. Fake Discount & Deceptive MRP Detector
- **Deal Quality Score (1 to 10)**: Categorizes prices into 💎 *Historic Low (10/10)*, 🔥 *Epic Deal (9/10)*, 🟢 *Great Price*, 🟡 *Fair Price*, and ⚠️ *Fake Discount Alert*.
- **MRP Inflation Defense**: Detects when merchants artificially inflate strikethrough MRP right before a sale to fake large markdowns.

### 📸 4. AI Vision Screenshot-to-Track
- No link copying required. Forward or upload a screenshot of an Amazon/Flipkart product page or a photo of a physical supplement jar.
- Multimodal AI extracts title, brand, variant, and price, then automatically scans all stores to find the best live deals.

### 📈 5. TradingView Financial Charts in Telegram Mini App (TMA)
- Tap **`[ 📱 Interactive Dashboard ]`** on any tracked item to launch an in-app **TradingView Lightweight-Charts** financial canvas.
- Features smooth hardware-accelerated touch zoom, horizontal panning, magnetized crosshairs, and live 30-day statistical bands.

### 📣 6. Multi-Channel Push Notifications (`/channels`)
- Powered by `apprise` (supporting 90+ alert services).
- Simultaneously routes restock and price drop notifications to **Discord Webhooks, NTFY push topics, Slack, Pushover, custom Webhooks, and Email** alongside Telegram.

### 🥛 7. Amul Warehouse High-Frequency Engine
- Sub-minute StoreHippo polling for high-demand Amul protein restocks (Lassi, Buttermilk, Whey, Paneer).
- Dynamic stock alerts on warehouse quantity decreases (e.g. 154 units → 120 units remaining).
- Automated cart reservation and `/autoorder` integration.

### 🛡️ 8. Self-Healing & Stealth Infrastructure
- **Cashews Cache**: Anti-stampede query locks (`lock=True`) prevent duplicate requests and IP bans.
- **Scrapling Adaptive Parser**: Self-healing DOM parser relocates elements dynamically when store CSS class names change.
- **Camoufox C++ Anti-Detect**: Native C++ Firefox engine evading bot mitigation systems on cloud hosts.
- **Observability**: Real-time Prometheus metrics at `/metrics` and Sentry error tracing.

---

## 🏛️ Architecture Overview

```mermaid
flowchart TD
    subgraph Ingestion ["1. Data Ingestion & Scrapers"]
        A1["curl_cffi TLS Engine<br/>(Amazon, Flipkart)"]
        A2["Next.js SSR Harvester<br/>(HyugaLife, HealthKart, MB)"]
        A3["Shopify Predictive API<br/>(Nakpro, AS-IT-IS)"]
        A4["Stealth Browser / Playwright<br/>(Amul, StoreHippo)"]
        A5["Scrapling Adaptive Parser<br/>(Self-Healing Fallback)"]
    end

    subgraph Core ["2. Core Intelligence & Processing"]
        B1["Cashews Cache<br/>(Anti-Stampede & TTL)"]
        B2["Discovery & Normalizer<br/>(rapidfuzz, Brand Guard)"]
        B3["DealScorer Engine<br/>(Fake Discount Detection)"]
        B4["CheckOrchestrator<br/>(Postgres SKIP LOCKED)"]
    end

    subgraph Storage ["3. Data Layer"]
        C1[("Supabase PostgreSQL<br/>Integer-Paise Accounting")]
    end

    subgraph Delivery ["4. Presentation & Delivery"]
        D1["Telegram Bot (@wheypricewatch_bot)<br/>PTB 22.8 Async Engine"]
        D2["FastAPI Mini App (TMA)<br/>TradingView Charts"]
        D3["Apprise Multi-Channel<br/>Discord / NTFY / Slack"]
        D4["Prometheus Metrics (/metrics)<br/>Sentry Tracing"]
    end

    Ingestion --> B1 --> B2 --> B3 --> C1
    B4 --> Ingestion
    C1 --> Delivery
```

---

## 🛠️ Complete Telegram Command Reference

| Command | Description |
| :--- | :--- |
| `/start` | Home dashboard, live system overview, and interactive navigation menu |
| `/track <url>` | Track any product link with auto or custom target price |
| `/compare <query>` | Find the lowest price and live stock across all 7+ trusted stores |
| `/tracked` or `/list` | List all your active tracked products with live prices and status badges |
| `/check` | Perform an instant live price and stock refresh across all tracked items |
| `/untrack <id>` | Stop tracking a product and cancel notifications |
| `/history [id]` | Generate a dark-themed price fluctuation graph |
| `/channels` | Manage multi-channel alerts (`/channels add ntfy://topic`, `/channels test`) |
| `/settings` | Configure repeat alert limits (1x, 2x, 3x, 5x, Until OOS) and tracking modes |
| `/pincode [pin]` | View or update your default delivery pincode (e.g. `/setpincode 110001`) |
| `/products` or `/amul` | Browse Amul protein categories and real-time stock levels |
| `/search <query>` | Search Amul catalog by keyword (e.g. `/search lassi`) |
| `/trackall` | Toggle 1-click restock alerts for **ALL** Amul protein products |
| `/favourites` | List and manage your starred favourite products |
| `/count` | Real-time warehouse inventory counts per SKU |
| `/analytics` | View Amul restock statistics and in-stock ratios |
| `/map` | View regional warehouse delivery hubs |
| `/status` | View system operational health and scraping intervals |
| `/support` | Support guide and community links |

---

## 💻 Tech Stack

- **Runtime**: Python 3.12+ (tested on Python 3.15)
- **Bot Framework**: `python-telegram-bot[webhooks,rate-limiter]` v22.8
- **Web & Mini App**: `fastapi`, `uvicorn`, `tradingview-lightweight-charts`
- **HTTP & Scraping**: `curl_cffi`, `httpx[http2]`, `selectolax`, `scrapling`, `playwright`, `camoufox`
- **Caching & Resilience**: `cashews` (Anti-stampede, in-memory & Redis support), `tenacity`
- **Fuzzy Matching**: `rapidfuzz`
- **Notifications**: `apprise` (Discord, NTFY, Slack, Pushover, Webhooks)
- **Monitoring**: `prometheus-client`, `sentry-sdk`, `structlog`
- **Database**: PostgreSQL (Supabase) with atomic `FOR UPDATE SKIP LOCKED` lease locks

---

## 🧪 Testing

The test suite runs 100% offline using deterministic mocks and recorded HTTP fixtures.

```bash
# Run the entire test suite (162 tests)
pytest tests -q

# Run specific functional suites
pytest tests/unit/test_cross_store_discovery.py -v
pytest tests/unit/test_deal_scorer_and_vision.py -v
pytest tests/unit/test_architectural_enhancements.py -v
pytest tests/unit/test_end_to_end_bot_flow.py -v
```

---

## 🚀 Setup & Local Development

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/prabhav22-stack/PriceWatch.git
cd PriceWatch

python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Configure Environment Variables
Create a `.env` file in the project root:
```env
TELEGRAM_BOT_TOKEN="your_bot_token"
DATABASE_URL="postgresql://user:password@host:5432/dbname"
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_KEY="your-anon-or-service-role-key"

# Optional enhancements
GEMINI_API_KEY="your_gemini_api_key"        # For AI Vision Screenshot Tracking
APPRISE_URLS="discord://webhook_id/token"   # Default multi-channel notifications
SENTRY_DSN="https://..."                    # Sentry error tracking
REDIS_URL="redis://localhost:6379/0"        # Distributed cache (defaults to memory)
WEBAPP_URL="https://your-domain.com"        # Base URL for Telegram Mini App
```

### 3. Run the Telegram Bot & WebApp
```bash
# Start bot polling
python -m pricewatch.main

# Start Telegram Mini App & Metrics Server
uvicorn pricewatch.webapp.server:app --host 0.0.0.0 --port 8000
```

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
