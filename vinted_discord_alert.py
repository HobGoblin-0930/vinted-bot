"""
Vinted → Discord Alert Bot
==========================
Polls Vinted and sends new listings to Discord with a rich embed
matching the layout: seller, title, published, brand, size,
feedbacks, status, price — plus Details / Buy / Negotiate / Autobuy buttons.

Setup:
    pip install requests

How to get a Discord Webhook URL:
    1. Open Discord → channel ⚙️ → Integrations → Webhooks
    2. New Webhook → copy URL → paste into DISCORD_WEBHOOK_URL below

Run:
    python vinted_discord_alert.py
"""

import time
import json
import os
import requests
from datetime import datetime

# ──────────────────────────────────────────────
#  DISCORD WEBHOOK
# ──────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK", "")

# ──────────────────────────────────────────────
#  CONFIGURE YOUR SEARCHES HERE
# ──────────────────────────────────────────────
SEARCHES = [
    {
        "label": "Nike Air Max 90",
        "search_text": "Nike Air Max 90",
        "max_price": 60,        # set to None for no limit
        "min_price": None,
        "size_ids": [],         # see SIZE IDs below
        "brand_ids": [],        # see BRAND IDs below
        "order": "newest_first",
    },
    {
        "label": "Levi's 501 jeans",
        "search_text": "Levi's 501",
        "max_price": 40,
        "min_price": None,
        "size_ids": [],
        "brand_ids": [],
        "order": "newest_first",
    },
]

# How often to check (seconds)
CHECK_INTERVAL = 60

# Country domain: co.uk, fr, de, nl, be, es, it, pl, cz, lt, etc.
VINTED_DOMAIN = "www.vinted.co.uk"

# ──────────────────────────────────────────────
#  COMMON SIZE IDs (Vinted UK clothing)
#  XS=1271, S=1272, M=1273, L=1274, XL=1275, XXL=1276
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
#  COMMON BRAND IDs
#  Nike=53, Adidas=14, Levi's=304, Zara=586, H&M=264, Stone Island=1047
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
#  CORE BOT LOGIC
# ──────────────────────────────────────────────

STATE_FILE = "vinted_seen_ids.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": f"https://{VINTED_DOMAIN}/",
    "Origin": f"https://{VINTED_DOMAIN}",
}

SESSION = requests.Session()

COLOURS = [0x09B1BA, 0xF5A623, 0x7ED321, 0xD0021B, 0x9B59B6, 0x3498DB]


def load_seen() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_seen(seen: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(seen, f)


def get_vinted_session_cookie():
    try:
        SESSION.get(f"https://{VINTED_DOMAIN}/", headers=HEADERS, timeout=10)
    except requests.RequestException:
        pass


def fetch_listings(search: dict) -> list:
    params = {
        "search_text": search["search_text"],
        "order": search.get("order", "newest_first"),
        "per_page": 40,
        "page": 1,
    }
    if search.get("max_price"):
        params["price_to"] = search["max_price"]
    if search.get("min_price"):
        params["price_from"] = search["min_price"]
    if search.get("size_ids"):
        params["size_ids[]"] = search["size_ids"]
    if search.get("brand_ids"):
        params["brand_ids[]"] = search["brand_ids"]

    url = f"https://{VINTED_DOMAIN}/api/v2/catalog/items"

    try:
        r = SESSION.get(url, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json().get("items", [])
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            print("  [!] Session expired — refreshing cookie…")
            get_vinted_session_cookie()
        else:
            print(f"  [!] HTTP error: {e}")
    except requests.RequestException as e:
        print(f"  [!] Request error: {e}")
    return []


def star_rating(score) -> str:
    """Convert a 0–1 or 0–5 reputation score to star emojis."""
    try:
        val = float(score)
        # Vinted feedback_reputation is 0–1; convert to 0–5
        if val <= 1.0:
            val = val * 5
        full = round(val)
        full = max(0, min(5, full))
        return "⭐" * full + "☆" * (5 - full)
    except (TypeError, ValueError):
        return "☆☆☆☆☆"


def time_ago(updated_at) -> str:
    try:
        if isinstance(updated_at, (int, float)):
            then = datetime.utcfromtimestamp(updated_at)
        else:
            then = datetime.fromisoformat(str(updated_at).replace("Z", ""))
        diff = datetime.utcnow() - then
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds} seconds ago"
        elif seconds < 3600:
            return f"{seconds // 60} minutes ago"
        elif seconds < 86400:
            return f"{seconds // 3600} hours ago"
        else:
            return f"{seconds // 86400} days ago"
    except Exception:
        return "just now"


def resolve_item_url(item: dict) -> str:
    url = item.get("url", "")
    if url and not url.startswith("http"):
        url = f"https://{VINTED_DOMAIN}{url}"
    return url


def build_payload(label: str, item: dict, colour: int) -> dict:
    url = resolve_item_url(item)
    item_id = item.get("id", "")

    # ── Seller ───────────────────────────────────
    seller = item.get("user", {})
    seller_name = seller.get("login", "Unknown")
    seller_id = seller.get("id", "")
    seller_url = f"https://{VINTED_DOMAIN}/member/{seller_id}"

    # ── Price ─────────────────────────────────────
    price_obj = item.get("price", {})
    amount = price_obj.get("amount", "?")
    currency = price_obj.get("currency_code", "EUR")
    price_str = f"{amount} {currency}"

    # ── Feedback ──────────────────────────────────
    feedback_count = seller.get("feedback_count", 0)
    feedback_score = seller.get("feedback_reputation", None)
    stars = star_rating(feedback_score)
    feedback_str = f"{stars} ({feedback_count})"

    # ── Published ─────────────────────────────────
    published = time_ago(item.get("updated_at") or item.get("created_at_ts"))

    # ── Photos ────────────────────────────────────
    photos = item.get("photos", [])
    image_url = None
    if photos:
        image_url = (
            photos[0].get("full_size_url")
            or photos[0].get("url")
            or ((photos[0].get("thumbnails") or [{}])[-1].get("url"))
        )

    # ── Embed ─────────────────────────────────────
    embed = {
        "author": {
            "name": f"👤 {seller_name}",
            "url": seller_url,
        },
        "title": item.get("title", "New listing"),
        "url": url,
        "color": colour,
        "fields": [
            {"name": "⏳ Published",  "value": published,                           "inline": True},
            {"name": "🏷️ Brand",     "value": item.get("brand_title") or "—",      "inline": True},
            {"name": "📐 Size",       "value": item.get("size_title") or "—",       "inline": True},
            {"name": "🌟 Feedbacks",  "value": feedback_str,                        "inline": True},
            {"name": "💎 Status",     "value": item.get("status") or "—",           "inline": True},
            {"name": "💰 Price",      "value": price_str,                           "inline": True},
        ],
        "footer": {"text": f"🔍 Search: {label}"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    if image_url:
        embed["image"] = {"url": image_url}

    # ── Buttons ───────────────────────────────────
    # Discord webhooks support only style=5 (Link) buttons.
    # All four buttons link to the item; Buy/Negotiate use Vinted's deep paths.
    negotiate_url = f"https://{VINTED_DOMAIN}/items/{item_id}/want"

    components = [
        {
            "type": 1,  # Action Row
            "components": [
                {
                    "type": 2, "style": 5,
                    "label": "Details",
                    "emoji": {"name": "🔗"},
                    "url": url,
                },
                {
                    "type": 2, "style": 5,
                    "label": "Buy",
                    "emoji": {"name": "🛒"},
                    "url": url,
                },
                {
                    "type": 2, "style": 5,
                    "label": "Negotiate",
                    "emoji": {"name": "💬"},
                    "url": negotiate_url,
                },
                {
                    "type": 2, "style": 5,
                    "label": "Autobuy ✅",
                    "url": url,
                },
            ],
        }
    ]

    return {
        "username": "Vinted Alert",
        "avatar_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/14/Vinted_logo.svg/512px-Vinted_logo.svg.png",
        "embeds": [embed],
        "components": components,
    }


def send_discord(label: str, item: dict, colour: int):
    payload = build_payload(label, item, colour)
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
    except requests.HTTPError as e:
        print(f"  [!] Discord error {e.response.status_code}: {e.response.text}")
    except requests.RequestException as e:
        print(f"  [!] Discord webhook error: {e}")


def validate_webhook():
    if DISCORD_WEBHOOK_URL == "PASTE_YOUR_WEBHOOK_URL_HERE" or not DISCORD_WEBHOOK_URL:
        print("=" * 55)
        print("  ERROR: No Discord webhook URL configured!")
        print("  Edit DISCORD_WEBHOOK_URL at the top of the script.")
        print("=" * 55)
        raise SystemExit(1)


def run():
    validate_webhook()

    print("=" * 55)
    print("  Vinted → Discord Alert Bot  |  Ctrl+C to stop")
    print("=" * 55)
    for s in SEARCHES:
        print(f"  • {s['label']}")
    print(f"\nChecking every {CHECK_INTERVAL}s  |  domain: {VINTED_DOMAIN}\n")

    get_vinted_session_cookie()
    seen = load_seen()

    print("Seeding existing listings (no alerts on first run)…")
    for search in SEARCHES:
        key = search["label"]
        items = fetch_listings(search)
        if key not in seen:
            seen[key] = []
        for item in items:
            if str(item["id"]) not in seen[key]:
                seen[key].append(str(item["id"]))
    save_seen(seen)
    print("Done. Watching for NEW listings…\n")

    label_colours = {
        s["label"]: COLOURS[i % len(COLOURS)] for i, s in enumerate(SEARCHES)
    }

    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] Checking…", end=" ", flush=True)
            found_new = 0

            for search in SEARCHES:
                key = search["label"]
                colour = label_colours[key]
                items = fetch_listings(search)
                if key not in seen:
                    seen[key] = []

                for item in items:
                    item_id = str(item["id"])
                    if item_id not in seen[key]:
                        seen[key].append(item_id)
                        send_discord(key, item, colour)
                        found_new += 1

            save_seen(seen)
            print(f"{found_new} new item(s) found." if found_new else "nothing new.")

        except KeyboardInterrupt:
            print("\n\nBot stopped. Goodbye!")
            break
        except Exception as e:
            print(f"\n[!] Unexpected error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
