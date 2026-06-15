#!/usr/bin/env python3
"""TON cross-DEX arbitrage SCANNER (signals only -- never trades, never touches a wallet)."""
import os
import sys
import json
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


def get_symbol(addr):
    try:
        url = f"{GT}/networks/{NETWORK}/tokens/{addr}"
        r = requests.get(url, headers=HEAD, timeout=30)
        r.raise_for_status()
        return r.json()["data"]["attributes"].get("symbol") or "?"
    except Exception:
        return "?"


def scan_token(addr):
    url = f"{GT}/networks/{NETWORK}/tokens/{addr}/pools"
    r = requests.get(url, headers=HEAD, timeout=30)
    r.raise_for_status()
    pools = r.json().get("data", [])

    venues = {}
    for p in pools:
        try:
            at = p["attributes"]
            rel = p.get("relationships", {})
            base_id = rel.get("base_token", {}).get("data", {}).get("id", "")
            quote_id = rel.get("quote_token", {}).get("data", {}).get("id", "")
            if addr_matches(base_id, addr):
                price = float(at.get("base_token_price_usd") or 0)
            elif addr_matches(quote_id, addr):
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

    if len(venues) < 2:
        return None

    vs = list(venues.values())
    cheap = min(vs, key=lambda v: v["price"])
    dear = max(vs, key=lambda v: v["price"])
    if cheap["price"] <= 0:
        return None
    gross = (dear["price"] - cheap["price"]) / cheap["price"] * 100.0
    if gross > MAX_SPREAD:
        return None
    net = gross - COST
    return {"gross": gross, "net": net, "buy": cheap, "sell": dear}


def pretty(dex):
    return dex.replace("_", " ").replace("v2", "").strip().title() or "DEX"


def main():
    if not TOKENS:
        print("No tokens to scan. Set ARB_TOKENS variable.")
        sys.exit(0)

    results = []
    for addr in TOKENS:
        try:
            res = scan_token(addr)
            if res:
                results.append((addr, res))
        except Exception as e:
            print(f"scan failed for {addr}: {e}")

    results.sort(key=lambda x: x[1]["net"], reverse=True)
    hits = [r for r in results if r[1]["net"] >= THRESHOLD]

    if not hits and EVENT != "workflow_dispatch":
        print("No opportunities above threshold; staying silent.")
        return

    if not hits:
        tg(f"🔎 <b>Arb scan</b>\nNo spread above {THRESHOLD:.1f}% net right now "
           f"(checked {len(TOKENS)} token(s), costs assumed ~{COST:.1f}%).")
        return

    lines = [f"📈 <b>Arb scan</b> — net of ~{COST:.1f}% costs", ""]
    for addr, r in hits:
        buy, sell = r["buy"], r["sell"]
        sym = get_symbol(addr)
        link = f"https://www.geckoterminal.com/{NETWORK}/tokens/{addr}"
        lines.append(
            f'<b>+{r["net"]:.2f}%</b> net — <b>{sym}</b> (gross {r["gross"]:.2f}%)\n'
            f'  buy {pretty(buy["dex"])} ${buy["price"]:.8f}\n'
            f'  sell {pretty(sell["dex"])} ${sell["price"]:.8f}\n'
            f'  liq ${buy["liq"]:,.0f} / ${sell["liq"]:,.0f}\n'
            f'  🔗 <a href="{link}">open token</a>'
        )
    lines.append("")
    lines.append("⚠️ Gross prices; real fill limited by liquidity & slippage. Not advice.")
    tg("\n".join(lines))
    print(f"Reported {len(hits)} opportunity(ies).")


if __name__ == "__main__":
    main()
