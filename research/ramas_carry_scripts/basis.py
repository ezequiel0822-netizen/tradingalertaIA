"""Descriptive annualized basis of Binance USDT-M quarterly futures vs spot (daily closes).
Uses fapi/v1/continuousKlines (CURRENT_QUARTER, NEXT_QUARTER) + spot api/v3/klines. No key.
Expiry: last Friday of Mar/Jun/Sep/Dec 08:00 UTC.
"""
import requests, pandas as pd, numpy as np, os
OUT = os.path.dirname(os.path.abspath(__file__))
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
START = int(pd.Timestamp("2024-10-01", tz="UTC").timestamp()*1000)


def kl(url, params):
    rows, t = [], START
    while True:
        p = dict(params, startTime=t, limit=1000 if "api.binance" in url else 1500, interval="1d")
        d = S.get(url, params=p, timeout=30).json()
        if not isinstance(d, list) or not d:
            if not isinstance(d, list): print(url, d)
            break
        rows += d
        nt = d[-1][0] + 1
        if len(d) < p["limit"]: break
        t = nt
    s = pd.Series({pd.to_datetime(r[0], unit="ms", utc=True): float(r[4]) for r in rows})
    return s


def last_friday(y, m):
    d = pd.Timestamp(year=y, month=m, day=1, tz="UTC") + pd.offsets.MonthEnd(0)
    while d.weekday() != 4: d -= pd.Timedelta(days=1)
    return d + pd.Timedelta(hours=8)

EXP = sorted(last_friday(y, m) for y in range(2024, 2028) for m in (3, 6, 9, 12))

def expiry_for(ts, which):
    # close of daily candle = ts + 1 day
    t = ts + pd.Timedelta(days=1)
    fut = [e for e in EXP if e > t]
    return fut[0] if which == "CURRENT_QUARTER" else fut[1]

res = {}
for pair in ["BTCUSDT", "ETHUSDT"]:
    spot = kl("https://api.binance.com/api/v3/klines", {"symbol": pair})
    for ct in ["CURRENT_QUARTER", "NEXT_QUARTER"]:
        f = kl("https://fapi.binance.com/fapi/v1/continuousKlines", {"pair": pair, "contractType": ct})
        df = pd.concat([spot.rename("S"), f.rename("F")], axis=1).dropna()
        df["exp"] = [expiry_for(i, ct) for i in df.index]
        df["dte"] = [(e - (i + pd.Timedelta(days=1))).total_seconds()/86400 for i, e in zip(df.index, df["exp"])]
        df = df[df.dte > 14]  # drop near-expiry noise / roll mismatches
        df["ann"] = (df.F/df.S - 1) * 365/df.dte
        res[(pair, ct)] = df
        g = df.groupby(df.index.to_period("Q"))["ann"].agg(["mean", "median", "count"])
        print(f"\n== {pair} {ct}  overall mean={df.ann.mean():.4f} median={df.ann.median():.4f} n={len(df)}")
        print((g.assign(mean=lambda x: (x["mean"]*100).round(2), median=lambda x: (x["median"]*100).round(2))).to_string())
        print("last 5:\n", df.tail(5)[["S", "F", "dte", "ann"]].to_string())
pd.concat({f"{k[0]}_{k[1]}": v for k, v in res.items()}).to_csv(os.path.join(OUT, "basis_daily.csv"))
