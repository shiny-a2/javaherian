# app.py
import os, json, re, math, logging
from typing import Dict, Any, List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import requests

# OpenAI SDK (>=1.40)
try:
    from openai import OpenAI
except Exception as e:
    OpenAI = None

# ---------- Config & Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("app")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-5").strip()

WC_BASE_URL = os.getenv("WC_BASE_URL", "").rstrip("/")
WC_KEY = os.getenv("WC_KEY", "").strip()
WC_SECRET = os.getenv("WC_SECRET", "").strip()

# Price presentation (e.g., IRR->Toman: divide by 10)
PRICE_DIVISOR = float(os.getenv("PRICE_DIVISOR", "10"))
CURRENCY_LABEL = os.getenv("CURRENCY_LABEL", "تومان")

# Safety knobs
RESULTS_LIMIT = int(os.getenv("RESULTS_LIMIT", "5"))
TELEGRAM_DISABLE_WEB_PREVIEW = os.getenv("TELEGRAM_DISABLE_WEB_PREVIEW", "false").lower() == "true"

if not TELEGRAM_BOT_TOKEN:
    log.warning("TELEGRAM_BOT_TOKEN is empty")
if not OPENAI_API_KEY:
    log.warning("OPENAI_API_KEY is empty")
if not WC_BASE_URL:
    log.warning("WC_BASE_URL is empty")
if not WC_KEY or not WC_SECRET:
    log.warning("WooCommerce credentials are empty")

bot = Bot(TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = FastAPI()

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY and OpenAI else None

# ---------- Utilities ----------
def add_thousands_sep(n: float) -> str:
    try:
        i = int(round(n))
        s = f"{i:,}".replace(",", "٬")  # Persian thousands separator
        return s
    except Exception:
        return str(n)

def safe_text(s: str) -> str:
    return (s or "").strip()

def to_toman(raw_price: Any) -> str:
    # WooCommerce returns price as string; we convert to float then divide
    try:
        if raw_price in (None, "", "0"):
            return f"0 {CURRENCY_LABEL}"
        val = float(raw_price)
        if PRICE_DIVISOR and PRICE_DIVISOR != 0:
            val = val / PRICE_DIVISOR
        return f"{add_thousands_sep(val)} {CURRENCY_LABEL}"
    except Exception:
        return f"{raw_price} {CURRENCY_LABEL}"

def wc_get(path: str, params: Dict[str, Any] = None):
    url = f"{WC_BASE_URL}/wp-json/wc/v3/{path.lstrip('/')}"
    params = params or {}
    params.update({"consumer_key": WC_KEY, "consumer_secret": WC_SECRET})
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def search_products(criteria: Dict[str, Any], limit: int = RESULTS_LIMIT) -> List[Dict[str, Any]]:
    # Sanitize query terms
    def clean(s):
        return re.sub(r"[^0-9A-Za-z\u0600-\u06FF\s\-\_]", " ", s or "")

    params: Dict[str, Any] = {
        "per_page": min(max(limit, 1), 10),
        "status": "publish",
        "orderby": "relevance",
        "order": "desc"
    }

    if "query" in criteria and criteria["query"]:
        params["search"] = clean(criteria["query"])[:80]

    # optional price filters (expect Woo currency; presentation uses to_toman)
    if criteria.get("min_price"):
        params["min_price"] = criteria["min_price"]
    if criteria.get("max_price"):
        params["max_price"] = criteria["max_price"]

    # Attributes and category can be mapped later via slugs/tax query if needed
    try:
        items = wc_get("products", params=params)
    except Exception as e:
        log.exception("WooCommerce error")
        return []

    # Keep only in-stock
    def is_in_stock(p: Dict[str, Any]) -> bool:
        if p.get("stock_status") == "instock":
            return True
        if p.get("manage_stock"):
            try:
                return (p.get("stock_quantity") or 0) > 0
            except Exception:
                return False
        return False

    in_stock = [p for p in items if is_in_stock(p)]
    return in_stock[:limit]

def format_products(products: List[Dict[str, Any]]) -> str:
    if not products:
        return "فعلاً موردی مطابق معیارها موجود نیست."
    lines = []
    for p in products:
        name = safe_text(p.get("name"))
        price = to_toman(p.get("price") or p.get("regular_price"))
        link = safe_text(p.get("permalink") or "")
        sku = safe_text(p.get("sku") or "")
        brand = ""
        try:
            # Optional: try to extract brand from attributes
            for attr in p.get("attributes", []):
                if attr.get("name", "").lower() in ("brand", "برند"):
                    if attr.get("options"):
                        brand = attr["options"][0]
                        break
        except Exception:
            pass
        meta = " | ".join([x for x in [brand, f"SKU: {sku}" if sku else ""] if x])
        line = f"• <b>{name}</b> — {price}{(' | ' + meta) if meta else ''}\n<a href='{link}'>مشاهده/خرید</a>"
        lines.append(line)
    return "\n\n".join(lines)

# ---------- GPT Planning (Structured Output) ----------
PRODUCT_SCHEMA = {
    "name": "ProductAdvisorSchema",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reply": {"type": "string", "description": "Natural language advice in Persian."},
            "action": {"type": "string", "enum": ["none", "search_products"]},
            "criteria": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                    "brand": {"type": "string"},
                    "min_price": {"type": "number"},
                    "max_price": {"type": "number"},
                    "attributes": {
                        "type": "array",
                        "items": {"type": "object", "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "string"}
                        }, "required": ["name","value"], "additionalProperties": False}
                    }
                }
            }
        },
        "required": ["reply", "action"]
    },
    "strict": True
}

SYSTEM_PROMPT = """تو یک دستیار فروش حرفه‌ای برای فروشگاه هستی.
- پاسخ‌هایت کوتاه، دقیق و محترمانه باشد.
- اگر برای توصیه خرید به اطلاعات بیشتری نیاز داری، حداکثر ۲ سؤال روشن‌کننده بپرس.
- هر زمان احتمال خرید وجود دارد، action=search_products و criteria را دقیق پر کن.
- بودجه را اگر کاربر گفت، در criteria بنویس (min_price/max_price)؛ واحد همان واحد ووکامرس است. نمایش تومان را بک‌اند انجام می‌دهد.
- اگر نتیجه جستجو خالی شد، جایگزین‌های نزدیک پیشنهاد بده.
"""

def call_gpt(user_text: str) -> Dict[str, Any]:
    if not client:
        # Fallback when OpenAI SDK not wired (for dry-run)
        return {"reply": "لطفاً یک ویژگی از محصول بگو تا جستجو کنم.", "action": "none"}
    try:
        resp = client.responses.create(
            model=MODEL_NAME,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}
            ],
            response_format={"type": "json_schema", "json_schema": PRODUCT_SCHEMA}
        )
        # Robust extraction
        data_json = None
        try:
            # new SDK often provides this:
            data_json = json.loads(resp.output_text)
        except Exception:
            # fallback: crawl structure
            try:
                t = resp.output[0].content[0].text
                data_json = json.loads(t)
            except Exception:
                pass
        if not isinstance(data_json, dict):
            raise ValueError("Invalid JSON from model")
        return data_json
    except Exception as e:
        log.exception("GPT planning failed")
        # Graceful degraded behavior
        return {"reply": "در پردازش درخواست مشکلی پیش آمد. لطفاً دوباره تلاش کن یا ویژگی‌های بیشتری بگو.", "action": "none"}

# ---------- Telegram Handlers ----------
@dp.message()
async def on_message(msg: types.Message):
    text = msg.text or ""
    plan = call_gpt(text)

    reply_parts = [safe_text(plan.get("reply", ""))]
    if plan.get("action") == "search_products":
        products = search_products(plan.get("criteria", {}) or {}, limit=RESULTS_LIMIT)
        if products:
            reply_parts.append("<b>پیشنهادهای موجود:</b>\n" + format_products(products))
        else:
            reply_parts.append("فعلاً موردی مطابق معیارها موجود نیست. مایل هستی معیارها را کمی تغییر دهیم؟")

    final_text = "\n\n".join([p for p in reply_parts if p]).strip() or "پیامت دریافت شد."
    await msg.answer(final_text, disable_web_page_preview=TELEGRAM_DISABLE_WEB_PREVIEW)

# ---------- FastAPI Endpoints ----------
@app.get("/", response_class=PlainTextResponse)
def root():
    return "ok"

@app.get("/healthz", response_class=JSONResponse)
def healthz():
    return {"ok": True}

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    update = types.Update.model_validate(await req.json(), strict=False)
    await dp.feed_update(bot, update)
    return {"ok": True}
