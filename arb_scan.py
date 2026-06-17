#!/usr/bin/env python3
"""TON multi-DEX arbitrage SCANNER (signals only -- read-only, no wallet, no trades)."""
import os
import sys
import requests

TG_TOKEN  = os.environ.get("TG_TOKEN")
TG_CHAT   = os.environ.get("TG_CHAT")
NETWORK   = os.environ.get("NETWORK", "ton")
TOKEN_ADDR = os.environ.get("TOKEN_ADDR", "")  # fallback: comma-separated list
DISCOVER_LIMIT = int(os.environ.get("DISCOVER_LIMIT") or 100)
THRESHOLD = float(os.environ.get("ARB_THRESHOLD") or 1.0)
COST      = float(os.environ.get("ARB_COST") or 1.2)
MIN_LIQ   = float(os.environ.get("ARB_MIN_LIQ") or 10000)
MAX_SPREAD = float(os.environ.get("ARB_MAX_SPREAD") or 5.0)

GT = "https://api.geckoterminal.com/api/v2"
HEAD = {"Accept": "application/json;version=20230203"}
EVENT = os.environ.get("GITHUB_EVENT_NAME", "")


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


def addr_matches(rel_id, addr):
    return addr.lower() in (rel_id or "").lower()


def pretty(dex):
    return dex.replace("_", " ").replace("v2", "").strip().title() or "DEX"


def symbol_from_name(name, is_base):
    try:
        parts = [p.strip() for p in name.split("/")]
        if len(parts) == 2:
            return parts[0] if is_base else parts[1]
    except Exception:
        pass
    return ""


def discover_tokens():
    """
    Auto-discover top TON tokens from GeckoTerminal.
    Returns token addresses.
    """
    found = set()
    print("🔍 Discovering tokens from GeckoTerminal...")
    try:
        url = f"{GT}/networks/{NETWORK}/trending_pools"
        resp = requests.get(url, headers=HEAD, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        pools = data.get("data", [])
        print(f"   Got {len(pools)} trending pools")

        for p in pools:
            try:
                rel = p.get("relationships", {})
                base = rel.get("base_token", {}).get("data", {}).get("id", "")
                quote = rel.get("quote_token", {}).get("data", {}).get("id", "")

                if "/tokens/" in base:
                    found.add(base.split("/tokens/")[-1])
                if "/tokens/" in quote:
                    found.add(quote.split("/tokens/")[-1])
            except Exception:
                continue

    except Exception as e:
        print("❌ discover failed:", e)

    result = list(found)[:DISCOVER_LIMIT]
    print(f"✅ Discovered {len(result)} unique tokens")
    return result


def get_token(addr):
    """Return (symbol, venues) for one token. venues = list per DEX, sorted by price."""
    url = f"{GT}/networks/{NETWORK}/tokens/{addr}/pools"
    try:
        resp = requests.get(url, headers=HEAD, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"   ⚠️ Failed to fetch pools for {addr}: {e}")
        return None, []

    pools = resp.json().get("data", [])
    if not pools:
        print(f"   ⚠️ No pools for {addr}")
        return None, []

    venues = {}
    symbol = ""
    for p in pools:
        try:
            at = p["attributes"]
            rel = p.get("relationships", {})
            base_id = rel.get("base_token", {}).get("data", {}).get("id", "")
            quote_id = rel.get("quote_token", {}).get("data", {}).get("id", "")
            if addr_matches(base_id, addr):
                price = float(at.get("base_token_price_usd") or 0)
                is_base = True
            elif addr_matches(quote_id, addr):
                price = float(at.get("quote_token_price_usd") or 0)
                is_base = False
            else:
                continue
            if not symbol:
                symbol = symbol_from_name(at.get("name", ""), is_base)
            liq = float(at.get("reserve_in_usd") or 0)
            if price <= 0 or liq < MIN_LIQ:
                continue
            dex = rel.get("dex", {}).get("data", {}).get("id", "dex?")
            if dex not in venues or liq > venues[dex]["liq"]:
                venues[dex] = {"price": price, "liq": liq, "dex": dex}
        except Exception:
            continue
    if not symbol:
        symbol = addr[:6] + "…" + addr[-4:]
    sorted_venues = sorted(venues.values(), key=lambda v: v["price"])
    print(f"   {symbol}: found {len(sorted_venues)} DEX venues (liq ≥ ${MIN_LIQ:,.0f})")
    return symbol, sorted_venues


def opp_from_venues(venues):
    if len(venues) < 2:
        return None
    cheap, dear = venues[0], venues[-1]
    if cheap["price"] <= 0:
        return None
    gross = (dear["price"] - cheap["price"]) / cheap["price"] * 100.0
    if gross > MAX_SPREAD:
        return None
    return {"gross": gross, "net": gross - COST, "buy": cheap, "sell": dear}


def venue_block(venues, buy_dex=None, sell_dex=None):
    out = []
    for v in venues:
        tag = ""
        if v["dex"] == buy_dex:
            tag = " 🟢 buy"
        elif v["dex"] == sell_dex:
            tag = " 🔴 sell"
        out.append(f'  {pretty(v["dex"])}: ${v["price"]:.8f} (liq ${v["liq"]:,.0f}){tag}')
    return "\n".join(out)


def main():
    print("🚀 TON Multi-DEX Arbitrage Scanner")
    print(f"   Network: {NETWORK}")
    print(f"   Discover limit: {DISCOVER_LIMIT}")
    print(f"   Min liquidity: ${MIN_LIQ:,.0f}")
    print(f"   Threshold: {THRESHOLD:.2f}% net")
    print(f"   Cost estimate: {COST:.2f}%")
    print(f"   Max spread: {MAX_SPREAD:.2f}%")

    # Try to get tokens from environment variable first (backward compatibility)
    tokens = []
    if TOKEN_ADDR:
        tokens = [t.strip() for t in TOKEN_ADDR.split(",") if t.strip()]
        print(f"📋 Using manual token list from TOKEN_ADDR ({len(tokens)} tokens)")

    if not tokens:
        tokens = discover_tokens()

    if not tokens:
        print("❌ No tokens discovered. Exiting.")
        return

    print(f"📊 Scanning {len(tokens)} tokens...\n")

    scanned = []  # (addr, symbol, venues)
    for i, addr in enumerate(tokens, 1):
        print(f"🔎 [{i}/{len(tokens)}] {addr[:10]}...")
        sym, venues = get_token(addr)
        if sym and venues:
            scanned.append((addr, sym, venues))
        else:
            print("   ⏭️  No usable pools, skipping.")

    if not scanned:
        print("❌ No tokens with at least 2 DEX pools above liquidity floor.")
        tg("No tokens with 2+ DEX pools found. Check liquidity thresholds.")
        return

    print(f"\n✅ Scanned {len(scanned)} tokens with 2+ DEX venues.")

    hits = []
    for addr, sym, venues in scanned:
        opp = opp_from_venues(venues)
        if opp and opp["net"] >= THRESHOLD:
            hits.append((addr, sym, venues, opp))
    hits.sort(key=lambda x: x[3]["net"], reverse=True)

    if hits:
        print(f"🎯 Found {len(hits)} arbitrage opportunity(ies)!")
        lines = [f"📈 <b>Multi-DEX Arb scan</b> — net of ~{COST:.1f}% costs", ""]
        for addr, sym, venues, opp in hits:
            link = f"https://www.geckoterminal.com/{NETWORK}/tokens/{addr}"
            lines.append(f'<b>+{opp["net"]:.2f}%</b> net — <b>{sym}</b> (gross {opp["gross"]:.2f}%)')
            lines.append(venue_block(venues, opp["buy"]["dex"], opp["sell"]["dex"]))
            lines.append(f'  🔗 <a href="{link}">open token</a>')
            lines.append("")
        lines.append("⚠️ Gross prices; real fill limited by liquidity & slippage. Not advice.")
        tg("\n".join(lines))
        print("✅ Signals sent to Telegram.")
        return

    print("ℹ️  No opportunities above threshold.")
    if EVENT != "workflow_dispatch":
        print("   Scheduled run — silent exit.")
        return

    # Manual run: send snapshot
    multi = [(a, s, v) for a, s, v in scanned if len(v) >= 2]
    multi.sort(key=lambda x: sum(z["liq"] for z in x[2]), reverse=True)

    lines = [f"🔎 <b>Multi-DEX Arb scan</b>",
             f"No spread above {THRESHOLD:.1f}% net (costs ~{COST:.1f}%).", ""]
    if multi:
        lines.append("Live multi-DEX view (top pairs):")
        lines.append("")
        for addr, sym, venues in multi[:3]:
            opp = opp_from_venues(venues)
            spr = f" — spread {opp['gross']:.2f}%" if opp else ""
            lines.append(f"<b>{sym}</b>{spr}")
            lines.append(venue_block(venues,
                         opp["buy"]["dex"] if opp else None,
                         opp["sell"]["dex"] if opp else None))
            lines.append("")
    else:
        lines.append("No token had pools on 2+ DEXs above the liquidity floor.")
    tg("\n".join(lines))
    print("📤 Snapshot sent to Telegram.")


if __name__ == "__main__":
    main()
