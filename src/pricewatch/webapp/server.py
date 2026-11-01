"""Telegram Mini App (TMA) and REST API Server powered by FastAPI.

Serves responsive mobile-first dark-mode dashboards with interactive Chart.js
price trends, multi-store comparison matrices, and Telegram WebApp integration.
"""

import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from pricewatch.domain.models import CanonicalListing, PriceObservation
from pricewatch.logging_setup import get_logger

logger = get_logger("webapp.server")

app = FastAPI(title="PriceWatch Telegram Mini App", version="2.0.0")

# In-memory reference to repository (populated by app runner)
_repo = None
_discovery_svc = None


def set_webapp_context(repo: Any, discovery_service: Any = None):
    """Set repository and discovery service context for the WebApp API."""
    global _repo, _discovery_svc
    _repo = repo
    _discovery_svc = discovery_service


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "PriceWatch TMA"}


@app.get("/api/v1/listing/{listing_id}")
async def get_listing_data(listing_id: int):
    """Return canonical listing metadata and price history observations."""
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

    return {
        "id": listing.id,
        "title": listing.product_title,
        "variant": listing.variant_title,
        "store": listing.provider_code.title(),
        "current_price_rs": (listing.last_price_paise / 100.0) if listing.last_price_paise else None,
        "mrp_rs": (listing.last_mrp_paise / 100.0) if listing.last_mrp_paise else None,
        "available": listing.last_available,
        "url": listing.canonical_url,
        "history": history,
    }


@app.get("/webapp/dashboard/{listing_id}", response_class=HTMLResponse)
async def serve_dashboard(listing_id: int):
    """Render interactive HTML5 / Chart.js dashboard for Telegram WebApp."""
    title = "Product Details"
    current_price = "0"
    mrp_price = ""
    store = "Store"
    stock_status = "In Stock"
    stock_color = "#10b981"
    url = "#"
    history_json = "[]"

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

        try:
            observations = await _repo.get_price_observations(listing_id, limit=50)
            valid_obs = [o for o in observations if o.price_paise is not None and o.observed_at]
            valid_obs.sort(key=lambda o: o.observed_at)
            
            import json
            history_pts = [
                {
                    "t": o.observed_at.strftime("%d %b, %H:%M"),
                    "y": round(o.price_paise / 100.0, 2),
                }
                for o in valid_obs
            ]
            if history_pts:
                history_json = json.dumps(history_pts)
        except Exception as exc:
            logger.warning("Could not build price points for WebApp", error=str(exc))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>{title} - PriceWatch</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
    body {{ background: var(--bg); color: var(--text); padding: 16px; min-height: 100vh; }}
    .header {{ margin-bottom: 20px; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; background: rgba(56, 189, 248, 0.15); color: var(--accent); margin-bottom: 8px; }}
    .stock-badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; background: {stock_color}22; color: {stock_color}; float: right; }}
    h1 {{ font-size: 19px; font-weight: 700; line-height: 1.35; margin-bottom: 8px; }}
    .price-row {{ display: flex; align-items: baseline; gap: 10px; margin-top: 10px; }}
    .current-price {{ font-size: 28px; font-weight: 800; color: #38bdf8; }}
    .mrp {{ font-size: 15px; color: var(--hint); text-decoration: line-through; }}
    .chart-card {{ background: var(--card-bg); border-radius: 16px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 20px rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); }}
    .chart-title {{ font-size: 14px; font-weight: 600; color: var(--hint); margin-bottom: 12px; display: flex; justify-content: space-between; }}
    .action-btn {{ display: block; width: 100%; padding: 14px; background: var(--accent); color: var(--accent-text); border: none; border-radius: 12px; font-size: 15px; font-weight: 700; text-align: center; text-decoration: none; cursor: pointer; transition: transform 0.1s ease, filter 0.1s ease; margin-top: 12px; }}
    .action-btn:active {{ transform: scale(0.98); filter: brightness(0.9); }}
    .footer-hint {{ font-size: 12px; color: var(--hint); text-align: center; margin-top: 24px; }}
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

  <div class="chart-card">
    <div class="chart-title">
      <span>Interactive Price Fluctuation</span>
      <span>Live Trend</span>
    </div>
    <canvas id="priceChart" height="200"></canvas>
  </div>

  <a href="{url}" target="_blank" class="action-btn" onclick="onOrderClick()">
    🛍️ Open in Store
  </a>

  <div class="footer-hint">
    ⚡ Monitored by PriceWatch Bot with Instant Restock & Deal Alerts
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

    const rawData = {history_json};
    const ctx = document.getElementById('priceChart').getContext('2d');

    const labels = rawData.length > 0 ? rawData.map(d => d.t) : ['Initial', 'Current'];
    const values = rawData.length > 0 ? rawData.map(d => d.y) : [{current_price.replace(',', '')}, {current_price.replace(',', '')}];

    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: labels,
        datasets: [{{
          label: 'Price (₹)',
          data: values,
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.12)',
          borderWidth: 2.5,
          tension: 0.35,
          fill: true,
          pointBackgroundColor: '#38bdf8',
          pointRadius: values.length > 15 ? 2 : 4,
          pointHoverRadius: 6,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            callbacks: {{
              label: (context) => ' ₹' + context.parsed.y
            }}
          }}
        }},
        scales: {{
          x: {{
            grid: {{ display: false }},
            ticks: {{ color: '#64748b', maxTicksLimit: 5 }}
          }},
          y: {{
            grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
            ticks: {{
              color: '#64748b',
              callback: (val) => '₹' + val
            }}
          }}
        }}
      }}
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)
