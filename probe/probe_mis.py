import json, time, glob, os, sys, urllib.request
sys.path.insert(0, 'scripts')
from intraday import market_of
tse = market_of()
q = json.load(open(sorted(glob.glob('data/quotes/*.json'))[-1]))['q']
codes = sorted(c for c in q if len(c) == 4 and c.isdigit())
out = {'n_codes': len(codes), 'tse': sum(c in tse for c in codes)}
def get(url, hdr=None):
    t = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=hdr or {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mis.twse.com.tw/stock/index.jsp'}), timeout=30)
        b = r.read(); return time.time() - t, r.status, b
    except Exception as e:
        return time.time() - t, str(e)[:120], b''
for bs in (50, 100, 200, 400):
    ex = '|'.join(f"{'tse' if c in tse else 'otc'}_{c}.tw" for c in codes[:bs])
    dt, st, b = get('https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch=' + ex)
    try: n = len(json.loads(b).get('msgArray', []))
    except Exception: n = None
    out[f'mis_batch_{bs}'] = {'sec': round(dt, 2), 'status': st, 'returned': n, 'url_len': len(ex)}
    time.sleep(2)
# full sweep with batch 200
t0 = time.time(); got = 0; req = 0
for i in range(0, len(codes), 200):
    ex = '|'.join(f"{'tse' if c in tse else 'otc'}_{c}.tw" for c in codes[i:i+200])
    dt, st, b = get('https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch=' + ex); req += 1
    try: got += len(json.loads(b).get('msgArray', []))
    except Exception: pass
    time.sleep(1)
out['full_sweep_200'] = {'sec': round(time.time() - t0, 1), 'requests': req, 'returned': got}
# Yahoo 台股 類股報價（非官方）
for name, url in [('yahoo_class', 'https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.getClassQuotes;exchange=TAI;offset=0;sectorId=24'),
                  ('yahoo_rank', 'https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;exchange=TAI;limit=100;offset=0;period=1D;sortBy=-changePercent'),
                  ('wantgoo', 'https://www.wantgoo.com/stock/twstock/stat'),
                  ('twse_home_stat', 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&type=MS')]:
    dt, st, b = get(url, {'User-Agent': 'Mozilla/5.0'})
    out[name] = {'sec': round(dt, 2), 'status': st, 'bytes': len(b), 'head': b[:300].decode('utf-8', 'replace')}
json.dump(out, open('probe/result.json', 'w'), ensure_ascii=False, indent=1)
