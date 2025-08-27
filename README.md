# Telegram Product Advisor Bot (FastAPI + aiogram + OpenAI + WooCommerce)

Production-ready webhook bot:
- GPT planning with **Structured Outputs** (Responses API)
- WooCommerce live inventory/price lookup
- Prices shown in **Toman** (configurable divisor/label)
- Dockerized + minimal FastAPI app with `/telegram/webhook`

## 1) Environment variables
Create `.env` (or set in your hosting panel):

```env
# --- Telegram ---
TELEGRAM_BOT_TOKEN=REPLACE_WITH_YOUR_TELEGRAM_TOKEN

# --- OpenAI ---
OPENAI_API_KEY=REPLACE_WITH_YOUR_OPENAI_KEY
OPENAI_MODEL_NAME=gpt-5

# --- WooCommerce ---
WC_BASE_URL=https://javaherian-gallery.com
WC_KEY=ck_xxx
WC_SECRET=cs_xxx

# --- Price presentation ---
PRICE_DIVISOR=10
CURRENCY_LABEL=تومان

# --- Optional ---
RESULTS_LIMIT=5
TELEGRAM_DISABLE_WEB_PREVIEW=false
```

> If your WooCommerce uses IRR internally, `PRICE_DIVISOR=10` converts it to Toman for display.

## 2) Deploy (Render/Railway/Docker)

### Render.com (quick)
1. New **Web Service** → Select repo/folder.
2. Runtime: **Docker** (this repo has a Dockerfile).
3. Set env vars above.
4. Deploy → get your public base URL, e.g. `https://your-service.onrender.com`.

### Railway (quick)
- Create a new service from repo/zip.
- Add the env vars.
- Ensure the Start Command is the Dockerfile default (uvicorn).

### Plain Docker
```bash
docker build -t tg-advisor .
docker run -p 8000:8000 --env-file .env tg-advisor
```

## 3) Set the Telegram webhook
Replace TOKEN and URL:
```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://YOUR_PUBLIC_URL/telegram/webhook"
```

Verify:
```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

## 4) Test
Open your bot in Telegram and send a message like:
> «ساعت غواصی ضدآب تا ۲۰۰ متر با بودجه ۵۰ تا ۷۰ میلیون»

The bot will:
1. Ask clarifying question (if needed)
2. Plan JSON via GPT
3. Query WooCommerce for live in-stock items
4. Return ranked suggestions with **Toman** prices & buy links

## Notes
- For best relevance, later map `brand/category/attributes` to your exact WooCommerce tax/attribute slugs.
- Logs appear in container stdout. Add a proper logger/ingestion if needed.
- Security: Keep tokens/keys in env vars only; rotate if shared publicly.
