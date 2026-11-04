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
import unicodedata
import urllib.parse
import urllib.request

# --- Telegram (bot @Oniwolt_bot) ---
# Hodnoty se berou z GitHub Secrets / proměnných prostředí; pokud tam nejsou,
# použijí se tyto. POZOR: token v kódu = kdokoli s přístupem k repu ovládá bota.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or "8817784786:AAFktjq6Wnh7OUM4CcAbpWHv9Ypu85rdcNo"
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or "-5475057208"  # víc příjemců: "ID1,ID2"

VENUE_SLUG = "onigirazu"
# Očekávané položky podle názvu (hledá se bez diakritiky a velkých písmen, stačí část názvu).
# Wolt vyprodanou položku z menu odebere, proto se hlídá, jestli každá z těchto položek v menu je.
# Změní-li se nabídka, uprav tento seznam.
WATCH = [
    # (název skupiny, slovo v kategorii pro hlášení nových položek nebo None, [očekávané položky])
    ("sendvičů", "onigirazu", [
        "Batát zelí",
        "Kimči tofu",
        "Mango-avokádo",
        "Tempeh špenát",
        "Brokolice kešu",
        "Spring",
    ]),
    ("polévek", None, [
        "Tom Kha malá",
        "Tom Kha velká",
    ]),
]

API_URL = (
    "https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/"
    f"venues/slug/{VENUE_SLUG}/assortment?language=cs"
)
STATUS_URL = (
    f"https://consumer-api.wolt.com/order-xp/web/v1/venue/slug/{VENUE_SLUG}/dynamic/"
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
    # TELEGRAM_CHAT_ID může obsahovat víc ID oddělených čárkou
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    errors = []
    for chat_id in [c.strip() for c in TELEGRAM_CHAT_ID.split(",") if c.strip()]:
        data = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
        ).encode()
        try:
            with urllib.request.urlopen(url, data=data, timeout=20) as r:
                r.read()
        except Exception as e:
            errors.append(f"{chat_id}: {e}")
    if errors:
        raise RuntimeError("; ".join(errors))


def venue_status() -> tuple[bool, str]:
    """Vrátí (lze_objednat, text)."""
    d = http_get_json(STATUS_URL)
    v = d["venue"]
    raw = d.get("venue_raw") or {}
    st = v.get("open_status") or v.get("delivery_open_status") or {}

    # 1) Mimo otevírací dobu
    if not st.get("is_open"):
        nxt = st.get("next_open", "")  # např. 2026-10-09T10:45:00+02:00
        when = f" – otevírá {nxt[8:10]}.{nxt[5:7]}. v {nxt[11:16]}" if len(nxt) >= 16 else ""
        return False, f"🔴 Zavřeno{when}"

    # 2) V otevírací době, ale podnik je na Woltu offline (jde jen naplánovat)
    meanings = {
        m.get("meaning")
        for s_ in (v.get("header") or {}).get("delivery_method_statuses") or []
        for m in s_.get("metadata") or []
    }
    if raw.get("alive") is False or not v.get("online", True) or "TEMPORARILY_OFFLINE" in meanings:
        return False, "⏸️ Dočasně offline – teď objednat nejde (jen naplánovat na později)"

    return True, f"🟢 Otevřeno (zavírá v {st.get('next_close_time_localized', '?')})"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def is_unavailable(item: dict) -> bool:
    # vypnuto/vyprodáno na Woltu, nebo nulový sklad
    return bool(item.get("disabled_info")) or item.get("purchasable_balance") == 0


def clean(name: str) -> str:
    return normalize(name).replace("novinka -", "").strip()


def check() -> str:
    try:
        is_open, status_line = venue_status()
    except Exception as e:
        is_open, status_line = True, f"⚠️ Stav otevření nezjištěn ({e})"

    data = http_get_json(API_URL)
    all_categories = data.get("categories", [])
    items = list(data.get("items", []))

    groups = []   # (popisek, dostupné, problémové [(název, důvod)], nové v menu)
    for label, cat_key, expected in WATCH:
        ok, bad, matched_ids = [], [], set()
        for exp in expected:
            hit = next((i for i in items if normalize(exp) in normalize(i.get("name", ""))), None)
            if hit is None:
                bad.append((exp, "chybí v menu"))
            else:
                matched_ids.add(hit["id"])
                if is_unavailable(hit):
                    bad.append((hit["name"], "nedostupné"))
                else:
                    ok.append(hit["name"])
        new = []
        if cat_key:
            by_id = {i["id"]: i for i in items}
            for c in all_categories:
                if cat_key in normalize(c.get("name", "")):
                    new += [by_id[i]["name"] for i in c.get("item_ids", [])
                            if i in by_id and i not in matched_ids and not is_unavailable(by_id[i])]
        groups.append((label, ok, bad, new, len(expected)))

    all_ok = all(not bad for _, _, bad, _, _ in groups)

    if not is_open:
        head = "🔴 Onigirazu teď nepřijímá objednávky."
    elif all_ok:
        head = "✅ Onigirazu: vše je k dispozici!"
    else:
        head = "❌ Onigirazu: něco chybí."

    lines = [head, status_line]
    for label, ok, bad, new, total in groups:
        lines += ["", f"{label}: {len(ok)}/{total}"]
        lines += [f"• {n}" for n in ok]
        lines += [f"✗ {n} ({why})" for n, why in bad]
        if new:
            lines += ["", "➕ Nové v menu (není v seznamu hlídaných):"] + [f"• {n}" for n in new]
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
