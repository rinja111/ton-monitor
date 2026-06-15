#!/usr/bin/env python3
"""Probe #2: recent large buyers of given TON tokens (read-only, signals only)."""
import os
import sys
import requests

TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT  = os.environ["TG_CHAT"]
NETWORK  = os.environ.get("NETWORK", "ton")
TOKENS   = [t.strip() for t in os.environ.get("BUYER_TOKENS", "").split(",") if t.strip()]
MIN_USD  = float(os.environ.get("BUYER_MIN_USD") or 50)   # only buys >= this
TOP_N    = int(os.environ.get("BUYER_TOP_N") or 5)        # top buyers per token

GT = "https://api.geckoterminal.com/api/v2"
HEAD = {"Accept": "application/json;version=20230203"}


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


def top_pool(addr):
    url = f"{GT}/networks/{NETWORK}/tokens/{addr}/pools"
    r = requests.get(url, headers=HEAD, timeout=30)
    r.raise_for_status()
    pools = r.json().get("data", [])
    if not pools:
        return None, "?"
    def vol(p):
        try: return float(p["attributes"]["volume_usd"]["h24"] or 0)
        except: return 0.0
    pools.sort(key=vol, reverse=True)
    best = pools[0]
    name = best["attributes"].get("name", "?")
    sym = name.split("/")[0].strip() if "/" in name else name
    return best["attributes"]["address"], sym


def buyers_for(pool_addr):
    url = f"{GT}/networks/{NETWORK}/pools/{pool_addr}/trades"
    params = {"trade_volume_in_usd_greater_than": MIN_USD}
    r = requests.get(url, headers=HEAD, params=params, timeout=30)
    r.raise_for_status()
    trades = r.json().get("data", [])
    buys = {}
    for t in trades:
        a = t["attributes"]
        if a.get("kind") != "buy":
            continue
        wallet = a.get("tx_from_address") or ""
        usd = float(a.get("volume_in_usd") or 0)
        if not wallet:
            continue
        buys[wallet] = buys.get(wallet, 0) + usd
    return sorted(buys.items(), key=lambda x: x[1], reverse=True)[:TOP_N]


def short(w):
    return w[:6] + "…" + w[-4:] if len(w) > 12 else w


def main():
    if not TOKENS:
        print("No tokens. Set BUYER_TOKENS.")
        sys.exit(0)

    lines = [f"🕵️ <b>Recent large buyers</b> (buys ≥${MIN_USD:.0f}, last 24h)", ""]
    found_any = False
    for addr in TOKENS:
        try:
            pool, sym = top_pool(addr)
            if not pool:
                continue
            buyers = buyers_for(pool)
            if not buyers:
                continue
            found_any = True
            lines.append(f"<b>{sym}</b>")
            for wallet, usd in buyers:
                link = f"https://tonviewer.com/{wallet}"
                lines.append(f'  ${usd:,.0f} — <a href="{link}">{short(wallet)}</a>')
            lines.append("")
        except Exception as e:
            print(f"failed for {addr}: {e}")

    if not found_any:
        tg("🕵️ <b>Recent large buyers</b>\nNo buys above threshold in last 24h "
           "for these tokens (or trades API returned nothing).")
        print("No buyers found.")
        return

    lines.append("⚠️ Current buyers, not pre-pump. Tap a wallet to inspect on Tonviewer. Not advice.")
    tg("\n".join(lines))
    print("Sent buyers.")


if __name__ == "__main__":
    main()
