import requests,pandas as pd,time,numpy as np
S=requests.Session()
exec(open('analyze.py').read().split('def per')[0])
out={}
for c in ['BTC','ETH']:
    rows=[]; before='2026-10-01T00:00:00Z'
    while True:
        dd=S.get('https://indexer.dydx.trade/v4/historicalFunding/'+c+'-USD',params={'limit':1000,'effectiveBeforeOrAt':before},timeout=30).json()['historicalFunding']
        if not dd: break
        rows+= [(x['effectiveAt'],float(x['rate'])) for x in dd]
        last=pd.Timestamp(dd[-1]['effectiveAt'])
        if last< pd.Timestamp('2024-10-01',tz='UTC'): break
        before=(last-pd.Timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%SZ'); time.sleep(0.2)
    s=pd.Series({pd.Timestamp(t):r for t,r in rows}).sort_index()
    s=s[(s.index>='2024-10-01')&(s.index<'2026-10-01')]
    dy=s.groupby(s.index.floor('D')).sum()
    q=lambda x: x.groupby(x.index.tz_localize(None).to_period('Q')).mean()*365*100
    print(c,'dYdX by quarter', q(dy).round(2).to_dict())
    sp=(d[('hyperliquid',c)]-dy).dropna()
    print(c,'HL-dYdX spread by quarter', q(sp).round(2).to_dict(), 'pct days>0', round((sp>0).mean()*100,1), 'worst30d', round((sp*365*100).rolling(30).mean().min(),2))
    sp2=(d[('binance',c)]-dy).dropna()
    print(c,'BN-dYdX spread by quarter', q(sp2).round(2).to_dict())
    print(c,'share of hours exactly 0 on dYdX', round((s==0).mean()*100,1))
    pd.DataFrame({'dydx':dy}).to_csv(f'dydx_{c}.csv')
