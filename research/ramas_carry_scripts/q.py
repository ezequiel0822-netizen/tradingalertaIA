exec(open('analyze.py').read().split('def per')[0])
for c in ['BTC','ETH','SOL','DOGE','XRP']:
    s=(d[('hyperliquid',c)]-d[('binance',c)]).dropna()*365*100
    q=s.groupby(s.index.tz_localize(None).to_period('Q')).mean().round(2)
    hlq=(d[('hyperliquid',c)].groupby(d.index.tz_localize(None).to_period('Q')).mean()*365*100).round(2)
    print(c,'HL-BN spread by quarter:',dict(zip(q.index.astype(str),q.values)))
    print(c,'HL funding by quarter   :',dict(zip(hlq.index.astype(str),hlq.values)))
    # worst 30d rolling spread
    print(c,'worst 30d rolling spread APR', round(s.rolling(30).mean().min(),2), ' worst 30d HL funding APR', round((d[('hyperliquid',c)]*365*100).rolling(30).mean().min(),2))
