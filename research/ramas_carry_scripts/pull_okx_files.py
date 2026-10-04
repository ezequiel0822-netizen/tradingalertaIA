import io, zipfile, os, time, requests, pandas as pd
OUT = os.path.dirname(os.path.abspath(__file__))
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
months = pd.period_range("2024-10", "2026-09", freq="M")
frames = []
for c in ["BTC", "ETH", "SOL", "DOGE", "XRP"]:
    ok = 0
    for m in months:
        u = f"https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/{m.year}{m.month:02d}/{c}-USDT-SWAP-fundingrates-{m.year}-{m.month:02d}.zip"
        r = S.get(u, timeout=60)
        if r.status_code != 200:
            print("miss", c, m, r.status_code); continue
        z = zipfile.ZipFile(io.BytesIO(r.content))
        for n in z.namelist():
            df = pd.read_csv(z.open(n))
            if ok == 0 and m == months[0]: print(c, n, df.columns.tolist(), df.head(2).to_dict("records"))
            df["coin"] = c
            frames.append(df)
        ok += 1
        time.sleep(0.1)
    print(c, "months ok", ok, flush=True)
df = pd.concat(frames)
df.to_csv(os.path.join(OUT, "funding_okx_files.csv"), index=False)
print(df.columns.tolist(), len(df))
