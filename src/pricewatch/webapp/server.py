"""Telegram Mini App (TMA) and REST API Server powered by FastAPI.

Features:
- TradingView Lightweight-Charts interactive financial-grade price chart.
- Deal Quality & Fake Discount detection badge.
- Mobile-first dark UI adhering to Telegram theme parameters.
- Prometheus metrics exporter at /metrics.
"""

import json
import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from pricewatch.config import settings
from pricewatch.domain.models import CanonicalListing, PriceObservation
from pricewatch.logging_setup import get_logger
from pricewatch.services.deal_scorer import DealScorer

logger = get_logger("webapp.server")

# Initialize Sentry if configured
if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=1.0,
            environment=settings.APP_ENV,
        )
        logger.info("Sentry initialized for error tracing")
    except Exception as exc:
        logger.warning("Failed to initialize Sentry", error=str(exc))

app = FastAPI(title="PriceWatch Telegram Mini App", version="2.1.0")

# Prometheus Metrics Definitions
METRIC_REQUESTS = Counter(
    "pricewatch_http_requests_total",
    "Total HTTP requests handled by webapp",
    ["method", "endpoint"],
)
METRIC_ACTIVE_LISTINGS = Gauge(
    "pricewatch_active_listings_count",
    "Number of actively monitored product listings",
)
METRIC_CHECK_LATENCY = Histogram(
    "pricewatch_check_duration_seconds",
    "Latency of store price checks in seconds",
    ["store"],
)

# In-memory reference to repository (populated by app runner)
_repo = None
_discovery_svc = None


def set_webapp_context(repo: Any, discovery_service: Any = None):
    """Set repository and discovery service context for the WebApp API."""
    global _repo, _discovery_svc
    _repo = repo
    _discovery_svc = discovery_service
    if _repo and hasattr(_repo, "listings"):
        METRIC_ACTIVE_LISTINGS.set(len(_repo.listings))


@app.get("/health")
async def health_check():
    METRIC_REQUESTS.labels(method="GET", endpoint="/health").inc()
    return {"status": "ok", "app": "PriceWatch TMA", "charts": "TradingView"}


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics scrape target."""
    if _repo and hasattr(_repo, "listings"):
        METRIC_ACTIVE_LISTINGS.set(len(_repo.listings))
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/listing/{listing_id}")
async def get_listing_data(listing_id: int):
    """Return canonical listing metadata and price history observations."""
    METRIC_REQUESTS.labels(method="GET", endpoint="/api/v1/listing").inc()
    if not _repo:
        raise HTTPException(status_code=503, detail="Repository context not initialized")

    listing = _repo.listings.get(listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    observations = await _repo.get_price_observations(listing_id, limit=100)
    history = [
        {
            "observed_at": (o.observed_at.isoformat() if o.observed_at else None),
            "price_rs": (o.price_paise / 100.0) if o.price_paise else None,
            "available": o.available,
            "stock_quantity": o.inventory_quantity,
        }
        for o in observations
        if o.price_paise is not None
    ]

    summary_30d = await _repo.get_30d_price_summary(listing_id) if hasattr(_repo, "get_30d_price_summary") else None
    deal_eval = DealScorer.evaluate_deal(
        current_price_paise=listing.last_price_paise or 0,
        mrp_paise=listing.last_mrp_paise,
        history_summary_30d=summary_30d,
    )

    return {
        "id": listing.id,
        "title": listing.product_title,
        "variant": listing.variant_title,
        "store": listing.provider_code.title(),
        "current_price_rs": (listing.last_price_paise / 100.0) if listing.last_price_paise else None,
        "mrp_rs": (listing.last_mrp_paise / 100.0) if listing.last_mrp_paise else None,
        "available": listing.last_available,
        "url": listing.canonical_url,
        "deal_score": deal_eval.deal_score,
        "deal_rating": deal_eval.rating_label,
        "is_fake_discount": deal_eval.is_fake_discount,
        "deal_summary": deal_eval.summary,
        "history": history,
    }


@app.get("/webapp/dashboard/{listing_id}", response_class=HTMLResponse)
async def serve_dashboard(listing_id: int):
    """Render interactive TradingView Lightweight-Charts dashboard for Telegram WebApp."""
    METRIC_REQUESTS.labels(method="GET", endpoint="/webapp/dashboard").inc()

    title = "Product Details"
    current_price = "0"
    mrp_price = ""
    store = "Store"
    stock_status = "In Stock"
    stock_color = "#10b981"
    url = "#"
    tv_data_json = "[]"
    min_price_str = "N/A"
    avg_price_str = "N/A"
    deal_badge = "⚪ Normal Price"
    deal_score_num = 5
    deal_summary = "Tracking live prices."

    if _repo and listing_id in _repo.listings:
        listing: CanonicalListing = _repo.listings[listing_id]
        title = f"{listing.product_title} ({listing.variant_title})" if listing.variant_title else listing.product_title
        store = listing.provider_code.title()
        url = listing.canonical_url or "#"
        if listing.last_price_paise:
            current_price = f"{listing.last_price_paise / 100.0:,.2f}"
        if listing.last_mrp_paise:
            mrp_price = f"₹{listing.last_mrp_paise / 100.0:,.2f}"
        if not listing.last_available:
            stock_status = "Out of Stock"
            stock_color = "#ef4444"

        # 30-Day Stats & Deal Scoring
        summary_30d = await _repo.get_30d_price_summary(listing_id) if hasattr(_repo, "get_30d_price_summary") else None
        if summary_30d:
            if summary_30d.get("min_price"):
                min_price_str = f"₹{summary_30d['min_price'] / 100.0:,.0f}"
            if summary_30d.get("avg_price"):
                avg_price_str = f"₹{summary_30d['avg_price'] / 100.0:,.0f}"

        deal_eval = DealScorer.evaluate_deal(
            current_price_paise=listing.last_price_paise or 0,
            mrp_paise=listing.last_mrp_paise,
            history_summary_30d=summary_30d,
        )
        deal_badge = deal_eval.rating_label
        deal_score_num = deal_eval.deal_score
        deal_summary = deal_eval.summary

        # Build TradingView data series (time: UNIX seconds, value: float)
        try:
            observations = await _repo.get_price_observations(listing_id, limit=100)
            valid_obs = [o for o in observations if o.price_paise is not None and o.observed_at]
            valid_obs.sort(key=lambda o: o.observed_at)

            # Deduplicate points by timestamp (TradingView requires strictly ascending unique times)
            seen_ts = set()
            tv_pts = []
            for o in valid_obs:
                ts = int(o.observed_at.timestamp())
                if ts not in seen_ts:
                    seen_ts.add(ts)
                    tv_pts.append({
                        "time": ts,
                        "value": round(o.price_paise / 100.0, 2),
                    })

            if len(tv_pts) == 1:
                # Add synthetic baseline point 1 hour earlier
                tv_pts.insert(0, {"time": tv_pts[0]["time"] - 3600, "value": tv_pts[0]["value"]})
            elif not tv_pts and listing.last_price_paise:
                import time
                now = int(time.time())
                val = round(listing.last_price_paise / 100.0, 2)
                tv_pts = [
                    {"time": now - 3600, "value": val},
                    {"time": now, "value": val},
                ]

            tv_data_json = json.dumps(tv_pts)
        except Exception as exc:
            logger.warning("Could not build TradingView points", error=str(exc))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>{title} - PriceWatch</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <!-- TradingView Lightweight Charts standalone production build -->
  <script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    :root {{
      --bg: var(--tg-theme-bg-color, #0f172a);
      --card-bg: var(--tg-theme-secondary-bg-color, #1e293b);
      --text: var(--tg-theme-text-color, #f8fafc);
      --hint: var(--tg-theme-hint-color, #94a3b8);
      --accent: var(--tg-theme-button-color, #38bdf8);
      --accent-text: var(--tg-theme-button-text-color, #ffffff);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
    body {{ background: var(--bg); color: var(--text); padding: 14px; min-height: 100vh; }}
    .header {{ margin-bottom: 14px; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; background: rgba(56, 189, 248, 0.15); color: var(--accent); margin-bottom: 6px; }}
    .stock-badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; background: {stock_color}22; color: {stock_color}; float: right; }}
    h1 {{ font-size: 18px; font-weight: 700; line-height: 1.35; margin-bottom: 8px; }}
    .price-row {{ display: flex; align-items: baseline; gap: 10px; margin-top: 6px; }}
    .current-price {{ font-size: 28px; font-weight: 800; color: #38bdf8; }}
    .mrp {{ font-size: 15px; color: var(--hint); text-decoration: line-through; }}

    /* Deal Quality Card */
    .deal-card {{ background: var(--card-bg); border-radius: 14px; padding: 12px 14px; margin: 12px 0; border: 1px solid rgba(255,255,255,0.06); }}
    .deal-header {{ display: flex; justify-content: space-between; align-items: center; font-size: 13px; font-weight: 700; margin-bottom: 6px; }}
    .deal-badge {{ color: #38bdf8; }}
    .deal-desc {{ font-size: 12px; color: var(--hint); line-height: 1.4; }}

    /* Stats Grid */
    .stats-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 12px 0; }}
    .stat-box {{ background: var(--card-bg); border-radius: 12px; padding: 10px 12px; border: 1px solid rgba(255,255,255,0.06); }}
    .stat-label {{ font-size: 11px; color: var(--hint); font-weight: 600; text-transform: uppercase; }}
    .stat-val {{ font-size: 16px; font-weight: 800; color: var(--text); margin-top: 2px; }}

    /* TradingView Chart Container */
    .chart-card {{ background: var(--card-bg); border-radius: 16px; padding: 14px 10px 10px 10px; margin: 14px 0; border: 1px solid rgba(255,255,255,0.06); }}
    .chart-title {{ font-size: 13px; font-weight: 700; color: var(--hint); margin-bottom: 10px; padding: 0 6px; display: flex; justify-content: space-between; align-items: center; }}
    #tvChart {{ width: 100%; height: 220px; }}

    .action-btn {{ display: block; width: 100%; padding: 14px; background: var(--accent); color: var(--accent-text); border: none; border-radius: 12px; font-size: 15px; font-weight: 700; text-align: center; text-decoration: none; cursor: pointer; transition: transform 0.1s ease; margin-top: 14px; }}
    .action-btn:active {{ transform: scale(0.98); }}
    .footer-hint {{ font-size: 11px; color: var(--hint); text-align: center; margin-top: 20px; }}
  </style>
</head>
<body>
  <div class="header">
    <span class="badge">{store}</span>
    <span class="stock-badge">{stock_status}</span>
    <h1>{title}</h1>
    <div class="price-row">
      <div class="current-price">₹{current_price}</div>
      <div class="mrp">{mrp_price}</div>
    </div>
  </div>

  <div class="deal-card">
    <div class="deal-header">
      <span>Deal Evaluation</span>
      <span class="deal-badge">{deal_badge}</span>
    </div>
    <div class="deal-desc">{deal_summary}</div>
  </div>

  <div class="stats-grid">
    <div class="stat-box">
      <div class="stat-label">30-Day Lowest</div>
      <div class="stat-val">{min_price_str}</div>
    </div>
    <div class="stat-box">
      <div class="stat-label">30-Day Average</div>
      <div class="stat-val">{avg_price_str}</div>
    </div>
  </div>

  <div class="chart-card">
    <div class="chart-title">
      <span>Interactive Price Trend</span>
      <span style="font-size: 11px; color: #38bdf8;">TradingView Engine</span>
    </div>
    <div id="tvChart"></div>
  </div>

  <a href="{url}" target="_blank" class="action-btn" onclick="onOrderClick()">
    🛍️ Open in Store
  </a>

  <div class="footer-hint">
    ⚡ Powered by PriceWatch TradingView Engine • Real-Time Stock & Deal Protection
  </div>

  <script>
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    if (tg) {{
      tg.ready();
      tg.expand();
    }}

    function onOrderClick() {{
      if (tg && tg.HapticFeedback) {{
        tg.HapticFeedback.impactOccurred('medium');
      }}
    }}

    const chartData = {tv_data_json};
    const chartContainer = document.getElementById('tvChart');

    if (window.LightweightCharts && chartContainer) {{
      const chart = LightweightCharts.createChart(chartContainer, {{
        width: chartContainer.clientWidth,
        height: 220,
        layout: {{
          background: {{ color: 'transparent' }},
          textColor: '#94a3b8',
          fontSize: 11,
        }},
        grid: {{
          vertLines: {{ color: 'rgba(255, 255, 255, 0.04)' }},
          horzLines: {{ color: 'rgba(255, 255, 255, 0.04)' }},
        }},
        rightPriceScale: {{
          borderColor: 'rgba(255, 255, 255, 0.08)',
        }},
        timeScale: {{
          borderColor: 'rgba(255, 255, 255, 0.08)',
          timeVisible: true,
          secondsVisible: false,
        }},
        crosshair: {{
          vertLine: {{ color: 'rgba(56, 189, 248, 0.5)', width: 1, style: 2 }},
          horzLine: {{ color: 'rgba(56, 189, 248, 0.5)', width: 1, style: 2 }},
        }}
      }});

      const areaSeries = chart.addAreaSeries({{
        topColor: 'rgba(56, 189, 248, 0.40)',
        bottomColor: 'rgba(56, 189, 248, 0.02)',
        lineColor: '#38bdf8',
        lineWidth: 2,
      }});

      if (chartData && chartData.length > 0) {{
        areaSeries.setData(chartData);
        chart.timeScale().fitContent();
      }}

      window.addEventListener('resize', () => {{
        chart.applyOptions({{ width: chartContainer.clientWidth }});
      }});
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)
