import time, os, requests, pandas as pd
OUT = os.path.dirname(os.path.abspath(__file__))
START = int(pd.Timestamp("2024-10-01", tz="UTC").timestamp() * 1000)
END = int(pd.Timestamp("2026-10-04", tz="UTC").timestamp() * 1000)
S = requests.Session()
allrows = []
for coin in ["ETH", "SOL", "DOGE", "XRP"]:
    rows, t, fails = [], START, 0
    while t < END:
        r = S.post("https://api.hyperliquid.xyz/info", json={"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": END}, timeout=30)
        try:
            d = r.json()
        except Exception:
            d = None
        if not isinstance(d, list):
            fails += 1
            print("retry", coin, r.status_code, str(r.text)[:100]); time.sleep(10)
            if fails > 10: break
            continue
        if not d: break
        rows += [(int(x["time"]), float(x["fundingRate"])) for x in d]
        t = int(d[-1]["time"]) + 1
        time.sleep(1.2)
    rows = sorted(set(rows))
    print(coin, len(rows), pd.to_datetime(rows[0][0], unit="ms"), pd.to_datetime(rows[-1][0], unit="ms"), flush=True)
    allrows += [("hyperliquid", coin, a, b) for a, b in rows]
pd.DataFrame(allrows, columns=["venue", "coin", "ts", "rate"]).to_csv(os.path.join(OUT, "funding_hl.csv"), index=False)
