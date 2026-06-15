#!/usr/bin/env python3
"""TON multi-DEX arbitrage SCANNER (signals only -- read-only, no wallet, no trades)."""
import os
import sys
import requests

TG_TOKEN  = os.environ["TG_TOKEN"]
TG_CHAT   = os.environ["TG_CHAT"]
NETWORK   = os.environ.get("NETWORK", "ton")
TOKENS    = [t.strip() for t in os.environ.get("ARB_TOKENS", os.environ.get("TOKEN_ADDR", "")).split(",") if t.strip()]
THRESHOLD = float(os.environ.get("ARB_THRESHOLD") or 1.0)
COST      = float(os.environ.get("ARB_COST") or 1.2)
MIN_LIQ   = float(os.environ.get("ARB_MIN_LIQ") or 10000)
MAX_SPREAD = float(os.environ.get("ARB_MAX_SPREAD") or 5.0)

GT = "https://api.geckoterminal.com/api/v2"
HEAD = {"Accept": "application/json;version=20230203"}
EVENT = os.environ.get("GITHUB_EVENT_NAME", "")


def tg(text):
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
    # pool name is like "SMONY / TON"; base is left, quote is right
    try:
        parts = [p.strip() for p in name.split("/")]
        if len(parts) == 2:
            return parts[0] if is_base else parts[1]
    except Exception:
        pass
    return ""


def get_token(addr):
    """Return (symbol, venues) for one token. venues = list per DEX, sorted by price."""
    url = f"{GT}/networks/{NETWORK}/tokens/{addr}/pools"
    r = requests.get(url, headers=HEAD, timeout=30)
    r.raise_for_status()
    pools = r.json().get("data", [])

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
    return symbol, sorted(venues.values(), key=lambda v: v["price"])


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
    if not TOKENS:
        print("No tokens to scan.")
        sys.exit(0)

    scanned = []  # (addr, symbol, venues)
    for addr in TOKENS:
        try:
            sym, venues = get_token(addr)
            scanned.append((addr, sym, venues))
        except Exception as e:
            print(f"scan failed for {addr}: {e}")

    hits = []
    for addr, sym, venues in scanned:
        opp = opp_from_venues(venues)
        if opp and opp["net"] >= THRESHOLD:
            hits.append((addr, sym, venues, opp))
    hits.sort(key=lambda x: x[3]["net"], reverse=True)

    if hits:
        lines = [f"📈 <b>Multi-DEX Arb scan</b> — net of ~{COST:.1f}% costs", ""]
        for addr, sym, venues, opp in hits:
            link = f"https://www.geckoterminal.com/{NETWORK}/tokens/{addr}"
            lines.append(f'<b>+{opp["net"]:.2f}%</b> net — <b>{sym}</b> (gross {opp["gross"]:.2f}%)')
            lines.append(venue_block(venues, opp["buy"]["dex"], opp["sell"]["dex"]))
            lines.append(f'  🔗 <a href="{link}">open token</a>')
            lines.append("")
        lines.append("⚠️ Gross prices; real fill limited by liquidity & slippage. Not advice.")
        tg("\n".join(lines))
        print(f"Reported {len(hits)} hit(s).")
        return

    if EVENT != "workflow_dispatch":
        print("No opportunities above threshold; silent.")
        return

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
    print("Snapshot sent.")


if __name__ == "__main__":
    main()
