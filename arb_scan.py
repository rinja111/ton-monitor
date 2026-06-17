#!/usr/bin/env python3
"""TON multi-DEX arbitrage SCANNER (signals only -- read-only, no wallet, no trades)."""
import os
import sys
import requests

TG_TOKEN  = os.environ.get("TG_TOKEN")
TG_CHAT   = os.environ.get("TG_CHAT")
NETWORK   = os.environ.get("NETWORK", "ton")
THRESHOLD = float(os.environ.get("ARB_THRESHOLD") or 1.0)
COST      = float(os.environ.get("ARB_COST") or 1.2)
MIN_LIQ   = float(os.environ.get("ARB_MIN_LIQ") or 10000)

GT = "https://api.geckoterminal.com/api/v2"
HEAD = {"Accept": "application/json;version=20230203"}

# Фиксированный список TON-токенов (можно добавить свои)
TOKENS = [
    "EQCxE6mUtQJKFnGfaROHKOa1P2yP1V-21cj6sRrVZt4GxhPw",  # NOT
    "EQDxyvPeJDo79P0BL-qmfCBtH2E6xyi4y_Cm8Y_oxjU6HbyP",  # DOGS
    "EQCM3bndy-6VJZs8HYRCLm5BMsEMR8Fb9X9aXvWYRThA1d5p",  # CATI
    "EQD0i3aZzZwXrTIXgVSWgLybi5JTY8o7NwJ81QJtY8b7AjsC",  # HMSTR
    "EQB-MPwrd1G6W9Y-CS2paeNey8CIM1m_fbL4dbr3Orn-NS01",  # TON (self)
]


def tg(text):
    if not TG_TOKEN or not TG_CHAT:
        print("❌ TG_TOKEN or TG_CHAT not set")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TG_CHAT, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=30)
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram send failed:", e)


def get_token(addr):
    """Получить цены с разных DEX для одного токена."""
    url = f"{GT}/networks/{NETWORK}/tokens/{addr}/pools"
    try:
        r = requests.get(url, headers=HEAD, timeout=30)
        r.raise_for_status()
        pools = r.json().get("data", [])
    except Exception as e:
        print(f"⚠️ {addr[:8]}... error: {e}")
        return None, []

    venues = {}
    symbol = addr[:6] + "…" + addr[-4:]
    for p in pools:
        try:
            at = p["attributes"]
            rel = p.get("relationships", {})
            base_id = rel.get("base_token", {}).get("data", {}).get("id", "")
            quote_id = rel.get("quote_token", {}).get("data", {}).get("id", "")

            if addr.lower() in (base_id or "").lower():
                price = float(at.get("base_token_price_usd") or 0)
            elif addr.lower() in (quote_id or "").lower():
                price = float(at.get("quote_token_price_usd") or 0)
            else:
                continue

            liq = float(at.get("reserve_in_usd") or 0)
            if price <= 0 or liq < MIN_LIQ:
                continue

            dex = rel.get("dex", {}).get("data", {}).get("id", "dex?")
            if dex not in venues or liq > venues[dex]["liq"]:
                venues[dex] = {"price": price, "liq": liq, "dex": dex}
        except Exception:
            continue

    if not venues:
        return None, []

    # Найдём символ из названия пула
    for p in pools:
        try:
            name = p["attributes"].get("name", "")
            if "/" in name:
                symbol = name.split("/")[0].strip()
                break
        except:
            pass

    return symbol, sorted(venues.values(), key=lambda v: v["price"])


def pretty(dex):
    return dex.replace("_", " ").replace("v2", "").strip().title() or "DEX"


def main():
    print("🚀 TON Arbitrage Scanner (fixed token list)")
    print(f"   Checking {len(TOKENS)} tokens...")

    results = []
    for addr in TOKENS:
        sym, venues = get_token(addr)
        if venues and len(venues) >= 2:
            results.append((addr, sym, venues))
            print(f"   {sym}: found {len(venues)} DEX venues")
        else:
            print(f"   {addr[:8]}...: insufficient pools")

    if not results:
        print("❌ No token with 2+ DEX pools.")
        tg("❌ Scanner: No tokens with 2+ DEX pools found. Check MIN_LIQ or tokens.")
        return

    # Отправим тестовое сообщение о количестве найденных токенов
    msg = f"🔍 Scanner found {len(results)} tokens with 2+ DEX pools.\n\n"
    for addr, sym, venues in results[:5]:
        msg += f"• {sym}: {len(venues)} DEXes\n"
    tg(msg.strip())
    print("✅ Test message sent. Check Telegram.")


if __name__ == "__main__":
    main()
