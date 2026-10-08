#!/usr/bin/env python3
"""
Zkontroluje na Woltu, jestli jsou v Onigirazu k dispozici všechny sendviče,
a pošle výsledek do Telegramu.

Nastavení (proměnné prostředí):
  TELEGRAM_BOT_TOKEN  – token od @BotFather
  TELEGRAM_CHAT_ID    – tvoje chat ID (zjistíš přes @userinfobot)

Spouštění každý den v 11:05 (crontab -e):
  CRON_TZ=Europe/Prague
  5 11 * * * TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy /usr/bin/python3 /cesta/onigirazu_check.py

Bez externích knihoven – stačí Python 3.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

# --- Telegram (bot @Oniwolt_bot) ---
# Hodnoty se berou z GitHub Secrets / proměnných prostředí; pokud tam nejsou,
# použijí se tyto. POZOR: token v kódu = kdokoli s přístupem k repu ovládá bota.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or "8817784786:AAFktjq6Wnh7OUM4CcAbpWHv9Ypu85rdcNo"
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or "8887757178"

VENUE_SLUG = "onigirazu"
CATEGORY_SLUG = "onigirazu-2"   # kategorie 🍙ONIGIRAZU na Woltu
EXPECTED_COUNT = 5

API_URL = (
    "https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/"
    f"venues/slug/{VENUE_SLUG}/assortment?language=cs"
)
WOLT_LINK = f"https://wolt.com/cs/cze/prague/restaurant/{VENUE_SLUG}"


def http_get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Accept-Language": "cs",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def send_telegram(text: str) -> None:
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with urllib.request.urlopen(url, data=data, timeout=20) as r:
        r.read()


def check() -> str:
    data = http_get_json(API_URL)

    category = next(
        (c for c in data.get("categories", []) if c.get("slug") == CATEGORY_SLUG),
        None,
    )
    if category is None:
        return f"⚠️ Onigirazu: kategorie sendvičů na Woltu nenalezena.\n{WOLT_LINK}"

    items = {i["id"]: i for i in data.get("items", [])}
    sandwiches = [items[i] for i in category.get("item_ids", []) if i in items]

    available = [s["name"] for s in sandwiches if not s.get("disabled_info")]
    unavailable = [s["name"] for s in sandwiches if s.get("disabled_info")]

    if len(available) >= EXPECTED_COUNT:
        head = f"✅ Onigirazu: všech {EXPECTED_COUNT} sendvičů je k dispozici!"
    else:
        head = (
            f"❌ Onigirazu: k dispozici jen {len(available)}/{EXPECTED_COUNT} sendvičů."
        )

    lines = [head, ""]
    lines += [f"• {n}" for n in available]
    if unavailable:
        lines += ["", "Nedostupné:"] + [f"✗ {n}" for n in unavailable]
    lines += ["", WOLT_LINK]
    return "\n".join(lines)


def main() -> None:
    try:
        msg = check()
    except Exception as e:  # síť, změna API apod.
        msg = f"⚠️ Onigirazu check selhal: {e}\n{WOLT_LINK}"
    print(msg)
    try:
        send_telegram(msg)
    except Exception as e:
        print(f"Odeslání do Telegramu selhalo: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
