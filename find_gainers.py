#!/usr/bin/env python3
"""Probe: find recently-pumped TON tokens via GeckoTerminal (read-only)."""
import os
import sys
import requests

TG_TOKEN  = os.environ["TG_TOKEN"]
TG_CHAT   = os.environ["TG_CHAT"]
NETWORK   = os.environ.get("NETWORK", "ton")
MIN_LIQ   = float(os.environ.get("GAIN_MIN_LIQ") or 10000)   # ignore thin pools
MIN_GAIN  = float(os.environ.get("GAIN_MIN_PCT") or 20)      # min 24h price gain %
TOP_N     = int(os.environ.get("GAIN_TOP_N") or 12)
PAGES     = int(os.environ.get("GAIN_PAGES") or 5)

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


def token_addr(rel):
    raw = rel.get("base_token", {}).get("data", {}).get("id", "")
    # id looks like "ton_EQAbc..."
    if "_" in raw:
        return raw.split("_", 1)[1]
    return raw


def main():
    seen = {}
    for page in range(1, PAGES + 1):
        try:
            url = f"{GT}/networks/{NETWORK}/pools?page={page}"
            r = requests.get(url, headers=HEAD, timeout=30)
            r.raise_for_status()
            pools = r.json().get("data", [])
        except Exception as e:
            print(f"page {page} failed: {e}")
            continue

        for p in pools:
            try:
                at = p["attributes"]
                rel = p.get("relationships", {})
                liq = float(at.get("reserve_in_usd") or 0)
                if liq < MIN_LIQ:
                    continue
                chg = at.get("price_change_percentage", {}) or {}
                g = float(chg.get("h24") or 0)
                if g < MIN_GAIN:
                    continue
                addr = token_addr(rel)
                name = at.get("name", "?")
                sym = name.split("/")[0].strip() if "/" in name else name
                # keep the strongest pool per token
                if addr not in seen or g > seen[addr]["gain"]:
                    seen[addr] = {"sym": sym, "gain": g, "liq": liq, "addr": addr}
            except Exception:
                continue

    rows = sorted(seen.values(), key=lambda x: x["gain"], reverse=True)[:TOP_N]

    if not rows:
        tg(f"🔎 <b>TON gainers probe</b>\nNo tokens up ≥{MIN_GAIN:.0f}% (24h) "
           f"with liq ≥${MIN_LIQ:,.0f} right now.\n"
           f"(Either quiet market, or API can't surface gainers — that's the test.)")
        print("No gainers.")
        return

    lines = [f"🚀 <b>TON gainers (24h)</b> — liq ≥${MIN_LIQ:,.0f}", ""]
    for x in rows:
        lines.append(
            f'<b>{x["sym"]}</b>  ▲{x["gain"]:.1f}%  (liq ${x["liq"]:,.0f})\n'
            f'  <code>{x["addr"]}</code>'
        )
    lines.append("")
    lines.append("⚠️ 24h gainers, not 7d (free API limit). Probe only — not advice.")
    tg("\n".join(lines))
    print(f"Sent {len(rows)} gainers.")


if __name__ == "__main__":
    main()
