#!/usr/bin/env python3
"""TON arbitrage scanner via DexScreener (auto-discovery)."""
import os
import sys
import requests
import time

TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT = os.environ.get("TG_CHAT")
DISCOVER_LIMIT = int(os.environ.get("DISCOVER_LIMIT") or 20)
THRESHOLD = float(os.environ.get("ARB_THRESHOLD") or 1.0)
COST = float(os.environ.get("ARB_COST") or 1.2)
MIN_LIQ = float(os.environ.get("ARB_MIN_LIQ") or 10000)

DS = "https://api.dexscreener.com/latest/dex"


def tg(text):
    if not TG_TOKEN or not TG_CHAT:
        print("❌ TG_TOKEN or TG_CHAT not set")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TG_CHAT,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=30)
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram send failed:", e)


def discover_tokens():
    """Найти активные токены на TON через DexScreener."""
    found = set()
    print("🔍 Discovering tokens from DexScreener...")
    try:
        # DexScreener не имеет прямого эндпоинта для сети,
        # но мы можем использовать поиск по паре 'TON'
        url = f"{DS}/search?q=TON"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        pairs = data.get("pairs", [])

        for p in pairs:
            chain = p.get("chainId", "")
            if chain.lower() != "ton":
                continue
            base = p.get("baseToken", {})
            addr = base.get("address", "")
            if addr:
                found.add(addr)

        # Если нашли мало, добавим ручной список известных токенов
        if len(found) < 3:
            known = [
                "EQCxE6mUtQJKFnGfaROHKOa1P2yP1V-21cj6sRrVZt4GxhPw",
                "EQDxyvPeJDo79P0BL-qmfCBtH2E6xyi4y_Cm8Y_oxjU6HbyP",
                "EQCM3bndy-6VJZs8HYRCLm5BMsEMR8Fb9X9aXvWYRThA1d5p",
                "EQD0i3aZzZwXrTIXgVSwgLybi5JTY8o7NwJ81QJtY8b7AjsC",
                "EQB-MPwrd1G6W9Y-CS2paeNey8CIM1m_fbL4dbr3Orn-NS01",
            ]
            found.update(known)

    except Exception as e:
        print("❌ discover failed:", e)

    result = list(found)[:DISCOVER_LIMIT]
    print(f"✅ Discovered {len(result)} tokens")
    return result


def get_pools_dexscreener(addr):
    """Получить все пулы для токена через DexScreener."""
    url = f"{DS}/tokens/{addr}"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("pairs", [])
    except Exception as e:
        return []


def main():
    print("🚀 TON Arbitrage Scanner (DexScreener auto-discovery)")
    print(f"   Discover limit: {DISCOVER_LIMIT}")
    print(f"   Min liquidity: ${MIN_LIQ:,.0f}")

    tokens = discover_tokens()
    if not tokens:
        print("❌ No tokens found")
        tg("❌ No tokens discovered. Check DexScreener API.")
        return

    print(f"\n📊 Scanning {len(tokens)} tokens...\n")
    results = []

    for i, addr in enumerate(tokens, 1):
        print(f"🔎 [{i}/{len(tokens)}] {addr[:10]}...")
        pairs = get_pools_dexscreener(addr)

        # Группируем по DEX
        dex_prices = {}
        for p in pairs:
            chain = p.get("chainId", "")
            if chain.lower() != "ton":
                continue
            dex = p.get("dexId", "unknown")
            price = float(p.get("priceUsd", 0))
            liq = float(p.get("liquidity", {}).get("usd", 0))
            if price <= 0 or liq < MIN_LIQ:
                continue
            if dex not in dex_prices or liq > dex_prices[dex]["liq"]:
                dex_prices[dex] = {"price": price, "liq": liq, "dex": dex}

        if len(dex_prices) < 2:
            print(f"   ⏭️  only {len(dex_prices)} DEX with sufficient liquidity")
            continue

        sym = pairs[0].get("baseToken", {}).get("symbol", addr[:8])
        venues = sorted(dex_prices.values(), key=lambda v: v["price"])
        results.append((addr, sym, venues))
        print(f"   ✅ {sym}: {len(venues)} DEX venues")

    if not results:
        msg = "❌ No token with 2+ DEX pools found. Check MIN_LIQ or tokens."
        print(msg)
        tg(msg)
        return

    # Отчёт в Telegram
    msg = f"🔍 Found {len(results)} tokens with 2+ DEX pools:\n\n"
    for addr, sym, venues in results[:5]:
        msg += f"• <b>{sym}</b>: {len(venues)} DEXes\n"
        for v in venues:
            msg += f"    {v['dex']}: ${v['price']:.6f} (liq ${v['liq']:,.0f})\n"
        msg += "\n"
    tg(msg.strip())
    print("✅ Report sent to Telegram.")


if __name__ == "__main__":
    main()
