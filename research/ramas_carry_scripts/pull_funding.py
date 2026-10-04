"""Pull funding history from public APIs (no key) for several venues.
Descriptive only. Saves parquet-less CSVs in scratchpad.
"""
import time, json, sys, os
import requests
import pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
START = int(pd.Timestamp("2024-10-01", tz="UTC").timestamp() * 1000)
END = int(pd.Timestamp("2026-10-04", tz="UTC").timestamp() * 1000)
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"


def binance(sym):
    rows, t = [], START
    while t < END:
        r = S.get("https://fapi.binance.com/fapi/v1/fundingRate",
                  params={"symbol": sym, "startTime": t, "limit": 1000}, timeout=30)
        d = r.json()
        if not isinstance(d, list) or not d:
            if not isinstance(d, list):
                print("binance err", d)
            break
        rows += [(int(x["fundingTime"]), float(x["fundingRate"])) for x in d]
        t = int(d[-1]["fundingTime"]) + 1
        if len(d) < 1000:
            break
        time.sleep(0.2)
    return rows


def bybit(sym):
    rows, end = [], END
    while True:
        r = S.get("https://api.bybit.com/v5/market/funding/history",
                  params={"category": "linear", "symbol": sym, "startTime": START, "endTime": end, "limit": 200}, timeout=30)
        d = r.json()["result"]["list"]
        if not d:
            break
        rows += [(int(x["fundingRateTimestamp"]), float(x["fundingRate"])) for x in d]
        mn = min(int(x["fundingRateTimestamp"]) for x in d)
        if mn <= START or len(d) < 200:
            break
        end = mn - 1
        time.sleep(0.15)
    return rows


def okx(inst):
    rows, after = [], None
    while True:
        p = {"instId": inst, "limit": 100}
        if after:
            p["after"] = after
        r = S.get("https://www.okx.com/api/v5/public/funding-rate-history", params=p, timeout=30)
        d = r.json().get("data", [])
        if not d:
            break
        rows += [(int(x["fundingTime"]), float(x["realizedRate"] or x["fundingRate"])) for x in d]
        mn = min(int(x["fundingTime"]) for x in d)
        if mn <= START:
            break
        after = str(mn)
        time.sleep(0.25)
    return rows


def bitget(sym):
    rows, page = [], 1
    while page < 200:
        r = S.get("https://api.bitget.com/api/v2/mix/market/history-fund-rate",
                  params={"symbol": sym, "productType": "usdt-futures", "pageSize": 100, "pageNo": page}, timeout=30)
        j = r.json()
        d = j.get("data") or []
        if not d:
            if page == 1:
                print("bitget resp", str(j)[:300])
            break
        rows += [(int(x["fundingTime"]), float(x["fundingRate"])) for x in d]
        if min(int(x["fundingTime"]) for x in d) <= START:
            break
        page += 1
        time.sleep(0.15)
    return rows


def hyperliquid(coin):
    rows, t = [], START
    while t < END:
        r = S.post("https://api.hyperliquid.xyz/info",
                   json={"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": END}, timeout=30)
        d = r.json()
        if not isinstance(d, list) or not d:
            break
        rows += [(int(x["time"]), float(x["fundingRate"])) for x in d]
        nt = int(d[-1]["time"]) + 1
        if nt <= t:
            break
        t = nt
        time.sleep(0.3)
    return rows


COINS = ["BTC", "ETH", "SOL", "DOGE", "XRP"]
VENUES = {
    "binance": lambda c: binance(f"{c}USDT"),
    "bybit": lambda c: bybit(f"{c}USDT"),
    "okx": lambda c: okx(f"{c}-USDT-SWAP"),
    "bitget": lambda c: bitget(f"{c}USDT"),
    "hyperliquid": lambda c: hyperliquid(c),
}

allrows = []
for v, fn in VENUES.items():
    for c in COINS:
        try:
            rows = fn(c)
        except Exception as e:
            print("ERR", v, c, e)
            rows = []
        rows = sorted(set(rows))
        if rows:
            print(f"{v:12s} {c:5s} n={len(rows):6d} first={pd.to_datetime(rows[0][0], unit='ms')} last={pd.to_datetime(rows[-1][0], unit='ms')}")
        else:
            print(f"{v:12s} {c:5s} EMPTY")
        allrows += [(v, c, t, r) for t, r in rows]
        sys.stdout.flush()

df = pd.DataFrame(allrows, columns=["venue", "coin", "ts", "rate"])
df.to_csv(os.path.join(OUT, "funding_all.csv"), index=False)
print("saved", len(df))
