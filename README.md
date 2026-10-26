# PriceWatch 2.0 🎯

A resilient, multi-store price tracking bot for Indian e-commerce platforms (Nakpro, MuscleBlaze, Amazon India, Amazon Fresh, and generic Schema.org/JSON-LD storefronts).

PriceWatch 2.0 is built on a **Clean / Hexagonal Architecture** with a database-coordinated hybrid execution model:
- **Interactive Telegram Bot**: Hosted as an asynchronous Web Service on Render (instant responses to user commands).
- **Background Price Checking**: Stateless worker runners triggered by GitHub Actions, coordinated via atomic PostgreSQL lease locks (`claim_due_listings(...)` using `FOR UPDATE SKIP LOCKED`).
- **Storage**: Supabase PostgreSQL with 6 normalized tables, RLS, and integer-paise accounting (zero floating-point comparison bugs).
- **Two-Stage Verification**: Automated re-check for extreme drops (>40% drop from 7-day median or <25% of MRP) to eliminate false-positive discount alerts.

---

## 🛠️ Telegram Commands

- `/start` - Welcome message & quick guide
- `/help` - Command documentation
- `/track <url> <target_price> [pincode]` - Onboard a product URL. Multi-variant products prompt an interactive inline keyboard to select exact flavor/size.
- `/list` - Display all currently tracked products with live prices and status
- `/untrack <id>` - Remove an item from tracking
- `/pincode <6-digit>` - Update default delivery pincode
- `/status` - Check operational status

---

## 🧪 Testing

The entire test suite is 100% offline, using recorded HTML and JSON fixtures with `respx`:

```bash
# Run all unit tests
pytest tests -v
```

---

## 🚀 Deployment

1. **Supabase Database**:
   - Execute [`migrations/001_initial_v2_schema.sql`](migrations/001_initial_v2_schema.sql) in your Supabase SQL Editor.
2. **Render Web Service**:
   - Connect repository to Render using Blueprint [`render.yaml`](render.yaml).
   - Inject `TELEGRAM_BOT_TOKEN` and `DATABASE_URL`.
3. **GitHub Actions Secrets**:
   - Set `DATABASE_URL` and `TELEGRAM_BOT_TOKEN` in GitHub Repository Secrets.
