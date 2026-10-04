import os, numpy as np, pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
a = pd.read_csv(os.path.join(D, "funding_all.csv"))
a = a[~((a.venue == "hyperliquid") & a.coin.isin(["ETH", "SOL", "DOGE", "XRP"]))]
a = a[a.venue != "okx"]  # replaced by monthly files
h = pd.read_csv(os.path.join(D, "funding_hl.csv"))
o = pd.read_csv(os.path.join(D, "funding_okx_files.csv")).rename(columns={"funding_rate": "rate", "funding_time": "ts"})
o["venue"] = "okx"; o = o[["venue", "coin", "ts", "rate"]]
df = pd.concat([a, h, o])
df["t"] = pd.to_datetime(df.ts, unit="ms", utc=True).dt.floor("h")
df = df[(df.t >= "2024-10-01") & (df.t < "2026-10-01")]
df = df.drop_duplicates(["venue", "coin", "t"])
# daily funding sum per venue (fraction per day, paid to shorts if positive)
d = df.assign(day=df.t.dt.floor("D")).groupby(["venue", "coin", "day"]).rate.sum().unstack(["venue", "coin"])

def per(x):
    return np.where(x.index < pd.Timestamp("2025-01-01", tz="UTC"), "2024Q4", np.where(x.index < pd.Timestamp("2026-01-01", tz="UTC"), "2025", "2026YTD(Q1-Q3)"))

print("=== Mean annualized funding (% APR, sum of daily funding *365/days), Oct-2024..Sep-2026")
tab = (d.groupby(per(d)).mean() * 365 * 100).T.round(2)
tab["full"] = (d.mean() * 365 * 100).round(2)
print(tab.unstack(0).to_string() if False else tab.to_string())

# bitget 3 months only: compare last 85 days all venues
rec = d[d.index >= pd.Timestamp("2026-07-08", tz="UTC")]
print("\n=== Last ~85 days (2026-07-08..2026-09-30) mean APR %")
print((rec.mean() * 365 * 100).round(2).unstack(0).to_string())

print("\n=== Cross-venue daily spread vs Binance (APR %): short venue X / long Binance => earn f_X - f_BN")
rows = []
for c in ["BTC", "ETH", "SOL", "DOGE", "XRP"]:
    for v in ["bybit", "okx", "hyperliquid"]:
        s = (d[(v, c)] - d[("binance", c)]).dropna()
        ann = s * 365 * 100
        ac1 = s.autocorr(1); ac7 = s.autocorr(7)
        # causal sign rule: sign of trailing-7d mean spread (yesterday), earn today's spread
        sig = np.sign(s.rolling(7).mean().shift(1))
        causal = (sig * s).dropna()
        switches = (sig.diff().abs() > 0).sum()
        rows.append(dict(coin=c, venue=v, n=len(s), mean_signed=ann.mean(), median=ann.median(), std_daily=ann.std(),
                         mean_abs_foresight=ann.abs().mean(), pct_pos=(s > 0).mean() * 100, ac1=ac1, ac7=ac7,
                         causal7_gross=causal.mean() * 365 * 100, switches=int(switches),
                         y2025=ann[(ann.index >= pd.Timestamp('2025-01-01', tz='UTC')) & (ann.index < pd.Timestamp('2026-01-01', tz='UTC'))].mean(),
                         y2026=ann[ann.index >= pd.Timestamp('2026-01-01', tz='UTC')].mean()))
print(pd.DataFrame(rows).round(2).to_string(index=False))

# max pairwise spread across all 4 full venues each day with perfect foresight (upper bound)
print("\n=== Upper bound: daily max-min across binance/bybit/okx/hyperliquid with perfect foresight, APR %")
for c in ["BTC", "ETH", "SOL", "DOGE", "XRP"]:
    m = d.xs(c, axis=1, level=1)[["binance", "bybit", "okx", "hyperliquid"]].dropna()
    rng = (m.max(axis=1) - m.min(axis=1)) * 365 * 100
    print(c, "mean", round(rng.mean(), 2), "2026YTD", round(rng[rng.index >= pd.Timestamp('2026-01-01', tz='UTC')].mean(), 2))

# HL interest-rate floor check: fraction of HL hours at exactly 0.00125%
hl = df[df.venue == "hyperliquid"]
print("\n=== HL share of hours at exactly the 0.00125%/h baseline:")
print(hl.groupby("coin").rate.apply(lambda x: round(((x - 1.25e-5).abs() < 1e-9).mean() * 100, 1)).to_string())
bn = df[df.venue == "binance"]
print("=== Binance share of 8h prints at exactly 0.01% baseline:")
print(bn.groupby("coin").rate.apply(lambda x: round(((x - 1e-4).abs() < 1e-9).mean() * 100, 1)).to_string())
