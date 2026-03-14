"""
Vinted → Discord Alert Bot
==========================
- Uses a Discord Bot Token for real working buttons
- Loops every 5 seconds for 55 seconds (12 checks per GitHub Actions run)
- Sends rich embeds with Details / Buy / Negotiate / Autobuy buttons

Setup:
    pip install requests

GitHub Secrets needed:
    DISCORD_BOT_TOKEN   — your bot token from discord.com/developers
    DISCORD_CHANNEL_ID  — right-click channel → Copy Channel ID
"""

import time
import json
import os
import requests
from datetime import datetime, timezone

# ──────────────────────────────────────────────
#  DISCORD CONFIG (loaded from GitHub secrets)
# ──────────────────────────────────────────────
DISCORD_BOT_TOKEN  = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")

# ──────────────────────────────────────────────
#  CONFIGURE YOUR SEARCHES HERE
# ──────────────────────────────────────────────
SEARCHES = [
    {
        "label": "Xbox Controller",
        "search_text": "xbox controller",
        "max_price": 15,
        "min_price": None,
        "size_ids": [],
        "brand_ids": [],
        "status_ids": [1, 2, 3, 4],  # 1=new without tags, 2=very good, 3=good, 4=satisfactory
        "order": "newest_first",
    },
]

# How often to check within each GitHub Actions run (seconds)
CHECK_INTERVAL = 5

# How long to run before exiting (seconds) — keep under 60 for GitHub Actions
RUN_DURATION = 55

# Country domain: co.uk  fr  de  nl  be  es  it  pl  cz  lt ...
VINTED_DOMAIN = "www.vinted.co.uk"
CURRENCY_SYMBOL = "£"

# ──────────────────────────────────────────────
#  COMMON SIZE IDs  (UK clothing)
#  XS=1271  S=1272  M=1273  L=1274  XL=1275  XXL=1276
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
#  COMMON BRAND IDs
#  Nike=53  Adidas=14  Levi's=304  Zara=586  H&M=264  Stone Island=1047
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
#  INTERNALS — no need to edit below
# ──────────────────────────────────────────────

STATE_FILE = "vinted_seen_ids.json"

VINTED_HEADERS = {
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

DISCORD_HEADERS = {
    "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    "Content-Type": "application/json",
}

COLOURS = [0x09B1BA, 0xF5A623, 0x7ED321, 0xD0021B, 0x9B59B6, 0x3498DB]

SESSION = requests.Session()


# ── State ──────────────────────────────────────

def load_seen() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_seen(seen: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(seen, f)


# ── Vinted API ─────────────────────────────────

def get_vinted_session_cookie():
    try:
        SESSION.get(f"https://{VINTED_DOMAIN}/", headers=VINTED_HEADERS, timeout=10)
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
    if search.get("status_ids"):
        params["status_ids[]"] = search["status_ids"]

    url = f"https://{VINTED_DOMAIN}/api/v2/catalog/items"
    try:
        r = SESSION.get(url, params=params, headers=VINTED_HEADERS, timeout=15)
        r.raise_for_status()
        return r.json().get("items", [])
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            print("  [!] Session expired — refreshing cookie...")
            get_vinted_session_cookie()
        else:
            print(f"  [!] HTTP error: {e}")
    except requests.RequestException as e:
        print(f"  [!] Request error: {e}")
    return []


# ── Discord helpers ────────────────────────────

def time_ago(epoch) -> str:
    if not epoch:
        return "Unknown"
    diff = int(time.time()) - int(epoch)
    if diff < 60:
        return f"{diff} second{'s' if diff != 1 else ''} ago"
    elif diff < 3600:
        m = diff // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    elif diff < 86400:
        h = diff // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    else:
        d = diff // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"


def star_rating(score) -> str:
    if score is None:
        return "No ratings"
    full = max(0, min(5, round(score * 5)))
    return "⭐" * full + "✩" * (5 - full)


def build_payload(label: str, item: dict, colour: int) -> dict:
    # Item URL
    url = item.get("url", "")
    if url and not url.startswith("http"):
        url = f"https://{VINTED_DOMAIN}{url}"

    # Seller
    user = item.get("user", {})
    seller = user.get("login", "Unknown seller")
    seller_id = user.get("id")
    seller_url = f"https://{VINTED_DOMAIN}/member/{seller_id}" if seller_id else url

    # Price
    price_obj = item.get("price", {})
    amount = price_obj.get("amount", "?")
    price_str = f"{CURRENCY_SYMBOL}{amount}"

    # Fields
    brand      = item.get("brand_title") or "—"
    size       = item.get("size_title")  or "—"
    condition  = item.get("status")      or "—"
    created_at = item.get("created_at_ts") or item.get("created_at")
    published  = time_ago(created_at)

    # Feedback
    feedback_score = user.get("feedback_reputation")
    feedback_count = user.get("positive_feedback_count", 0)
    stars          = star_rating(feedback_score)
    feedback_str   = f"{stars} ({feedback_count})"

    # Photo
    photos    = item.get("photos", [])
    image_url = None
    if photos:
        image_url = (
            photos[0].get("full_size_url")
            or photos[0].get("url")
            or (photos[0].get("thumbnails") or [{}])[-1].get("url")
        )

    embed = {
        "author": {"name": seller, "url": seller_url},
        "title": item.get("title", "New listing"),
        "url": url,
        "color": colour,
        "fields": [
            {"name": "⏳ Published", "value": published,    "inline": True},
            {"name": "🏷️ Brand",     "value": brand,        "inline": True},
            {"name": "📐 Size",       "value": size,         "inline": True},
            {"name": "⭐ Feedbacks",  "value": feedback_str, "inline": True},
            {"name": "💎 Status",     "value": condition,    "inline": True},
            {"name": "💰 Price",      "value": price_str,    "inline": True},
        ],
        "footer": {"text": f"🔍 Search: {label}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if image_url:
        embed["image"] = {"url": image_url}

    # Real working buttons via bot token
    components = [
        {
            "type": 1,
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
                    "url": url,
                },
                {
                    "type": 2, "style": 5,
                    "label": "Autobuy",
                    "emoji": {"name": "✅"},
                    "url": url,
                },
            ],
        }
    ]

    return {"embeds": [embed], "components": components}


def send_discord(label: str, item: dict, colour: int):
    payload = build_payload(label, item, colour)
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    try:
        r = requests.post(url, headers=DISCORD_HEADERS, json=payload, timeout=10)
        r.raise_for_status()
    except requests.HTTPError as e:
        print(f"  [!] Discord error {e.response.status_code}: {e.response.text}")
    except requests.RequestException as e:
        print(f"  [!] Discord error: {e}")


# ── Validation ─────────────────────────────────

def validate():
    errors = []
    if not DISCORD_BOT_TOKEN:
        errors.append("DISCORD_BOT_TOKEN secret is missing")
    if not DISCORD_CHANNEL_ID:
        errors.append("DISCORD_CHANNEL_ID secret is missing")
    if errors:
        print("=" * 55)
        for e in errors:
            print(f"  ERROR: {e}")
        print("=" * 55)
        raise SystemExit(1)


# ── Main loop ──────────────────────────────────

def run():
    validate()

    print("=" * 55)
    print("  Vinted -> Discord Alert Bot")
    print(f"  Checking every {CHECK_INTERVAL}s for {RUN_DURATION}s")
    print("=" * 55)
    for s in SEARCHES:
        print(f"  * {s['label']}")
    print()

    get_vinted_session_cookie()
    seen = load_seen()

    # Seed on very first run only
    first_run = not bool(seen)
    if first_run:
        print("First run — seeding existing listings (no alerts)...")
        for search in SEARCHES:
            key = search["label"]
            items = fetch_listings(search)
            seen.setdefault(key, [])
            for item in items:
                iid = str(item["id"])
                if iid not in seen[key]:
                    seen[key].append(iid)
        save_seen(seen)
        print("Done. Future runs will alert on new listings.\n")
        return

    label_colours = {
        s["label"]: COLOURS[i % len(COLOURS)] for i, s in enumerate(SEARCHES)
    }

    start_time = time.time()
    checks = 0

    while time.time() - start_time < RUN_DURATION:
        checks += 1
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] Check #{checks}...", end=" ", flush=True)
        found_new = 0

        for search in SEARCHES:
            key    = search["label"]
            colour = label_colours[key]
            items  = fetch_listings(search)
            seen.setdefault(key, [])

            for item in items:
                iid = str(item["id"])
                if iid not in seen[key]:
                    seen[key].append(iid)
                    send_discord(key, item, colour)
                    found_new += 1

        save_seen(seen)
        print(f"{found_new} new item(s)." if found_new else "nothing new.")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()

