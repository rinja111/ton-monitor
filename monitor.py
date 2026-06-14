#!/usr/bin/env python3
"""TON token buy/sell monitor -> Telegram alerts."""
import os
import sys
import json
import requests

TG_TOKEN   = os.environ["TG_TOKEN"]
TG_CHAT    = os.environ["TG_CHAT"]
TOKEN_ADDR = os.environ["TOKEN_ADDR"]
NETWORK    = os.environ.get("NETWORK", "ton")
POOL_ADDR  = os.environ.get("POOL_ADDR", "").strip()
MIN_USD    = float(os.environ.get("MIN_USD") or 0)
STATE_FILE = os.environ.get("STATE_FILE", "state/seen.json")

GT = "https://api.geckoterminal.com/api/v2"
HEAD = {"Accept": "application/json;version=20230203"}


def tg(text):
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


def get_symbol():
    try:
        url = f"{GT}/networks/{NETWORK}/tokens/{TOKEN_ADDR}"
        r = requests.get(url, headers=HEAD, timeout=30)
        r.raise_for_status()
        return r.json()["data"]["attributes"].get("symbol") or "TOKEN"
    except Exception:
        return "TOKEN"


def get_pool():
    if POOL_ADDR:
        return POOL_ADDR
    url = f"{GT}/networks/{NETWORK}/tokens/{TOKEN_ADDR}/pools"
    r = requests.get(url, headers=HEAD, timeout=30)
    r.raise_for_status()
    pools = r.json().get("data", [])
    if not pools:
        print("No pools found. The token may not have liquidity on a TON DEX yet.")
        sys.exit(0)

    def vol(p):
        try:
            return float(p["attributes"]["volume_usd"]["h24"] or 0)
        except Exception:
            return 0.0

    pools.sort(key=vol, reverse=True)
    return pools[0]["attributes"]["address"]


def get_trades(pool):
    url = f"{GT}/networks/{NETWORK}/pools/{pool}/trades"
    params = {}
    if MIN_USD > 0:
        params["trade_volume_in_usd_greater_than"] = MIN_USD
    r = requests.get(url, headers=HEAD, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def save_state(state):
    folder = os.path.dirname(STATE_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def format_trade(trade, symbol):
    a = trade["attributes"]
    kind = a.get("kind", "?")
    usd = float(a.get("volume_in_usd") or 0)
    header = "🟢 BUY" if kind == "buy" else "🔴 SELL"
    lines = [f"{header}  <b>{symbol}</b>", f"💵 ${usd:,.2f}"]
    price_usd = a.get("price_to_in_usd") or a.get("price_from_in_usd")
    if price_usd:
        try:
            lines.append(f"🏷 ${float(price_usd):.8f}")
        except Exception:
            pass
    txh = a.get("tx_hash", "")
    if txh:
        lines.append(f'🔗 <a href="https://tonviewer.com/transaction/{txh}">view tx</a>')
    if a.get("block_timestamp"):
        lines.append(f"🕒 {a['block_timestamp']}")
    return "\n".join(lines)


def main():
    pool = get_pool()
    symbol = get_symbol()
    trades = get_trades(pool)
    ids_now = [t["id"] for t in trades]
    state = load_state()

    if state is None:
        save_state({"seen": ids_now[:500]})
        tg(f"✅ <b>Monitoring started</b> for <b>{symbol}</b>\n"
           f"Pool: <code>{pool}</code>\n"
           f"You'll now get an alert on every new buy / sell.")
        print("Baseline saved.")
        return

    seen = set(state.get("seen", []))
    new = [t for t in trades if t["id"] not in seen]
    new.reverse()

    for t in new:
        tg(format_trade(t, symbol))

    merged = ids_now + [i for i in state.get("seen", []) if i not in ids_now]
    save_state({"seen": merged[:500]})
    print(f"Sent {len(new)} new alert(s).")


if __name__ == "__main__":
    main()
