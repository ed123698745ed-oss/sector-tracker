"""盤中快照（測試版）：從證交所「基本市況報導」查詢題材成分股的最新成交價，計算盤中上榜題材。

  python3 intraday.py test   抓一次，輸出抓取統計到 test/mis_result.txt（不存個股報價）
"""
import csv, datetime, glob, gzip, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import judge  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPE = datetime.timezone(datetime.timedelta(hours=8))
BATCH = 50


def members():
    from build import load_periods
    per, today = load_periods(), datetime.datetime.now(TPE).strftime('%Y%m%d')
    th = {}
    for r in list(csv.reader(open(f'{ROOT}/config/themes.csv', encoding='utf-8')))[1:]:
        a, b = per.get(r[0], ('', ''))
        if (a and today < a) or (b and today > b):  # 已過有效期間的題材不判斷
            continue
        th.setdefault(r[0], []).append(r[1])
    return th


def market_of():
    # 以最近一日上市原始檔判斷上市／上櫃
    f = sorted(glob.glob(f'{ROOT}/archive/raw/twse/*.json.gz'))[-1]
    tw = json.load(gzip.open(f, 'rt'))
    s = set()
    for t in tw.get('tables', []):
        if '每日收盤行情' in (t.get('title') or ''):
            s |= {r[0] for r in t['data']}
    return s


def fetch(codes, tse):
    out, stat = {}, {'requests': 0, 'errors': 0}
    ex = [f"{'tse' if c in tse else 'otc'}_{c}.tw" for c in codes]
    for i in range(0, len(ex), BATCH):
        u = 'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=' + '|'.join(ex[i:i + BATCH]) + f'&json=1&delay=0&_={int(time.time()*1000)}'
        for k in range(3):
            try:
                stat['requests'] += 1
                d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mis.twse.com.tw/stock/index.jsp'}), timeout=20).read())
                for x in d.get('msgArray', []):
                    out[x.get('c')] = x
                break
            except Exception as e:
                stat['errors'] += 1
                stat['last_error'] = str(e)[:200]
                time.sleep(3)
        time.sleep(1.5)
    return out, stat


def pct(x):
    """盤中漲跌%。當下無成交價時：今日累計量為 0 視為無成交；否則依序用最佳買價、最佳賣價
    （跌停鎖死時只剩賣價、漲停鎖死時只剩買價），都沒有就用漲跌停價判斷。"""
    try:
        y = float(x['y'])
        if not y:
            return None
        z = x.get('z', '-')
        if z in ('-', '', None):
            if float(x.get('v') or 0) <= 0:
                return None
            z = '-'
            for k in ('b', 'a'):
                v = (x.get(k) or '-').split('_')[0]
                if v not in ('-', ''):
                    z = v; break
            if z == '-':
                return None
        return round((float(z) - y) / y * 100, 2)
    except Exception:
        return None


def main():
    th = members()
    codes = sorted({c for v in th.values() for c in v})
    t0 = time.time()
    q, stat = fetch(codes, market_of())
    secs = round(time.time() - t0, 1)
    p = {c: pct(x) for c, x in q.items()}
    got = sum(v is not None for v in p.values())
    hits = []
    for t, cs in th.items():
        h = judge([p[c] for c in cs if p.get(c) is not None])
        if h:
            hits.append(f'{t}({h})')
    times = sorted({x.get('t') for x in q.values() if x.get('t')})
    lines = [
        f"run_at {datetime.datetime.now(TPE).strftime('%Y-%m-%d %H:%M:%S')}",
        f"codes {len(codes)} returned {len(q)} priced {got} seconds {secs}",
        f"requests {stat['requests']} errors {stat['errors']} last_error {stat.get('last_error','')}",
        f"quote_time_range {times[:1]} {times[-1:]}",
        f"hits {len(hits)} {' '.join(hits)}",
    ]
    os.makedirs(f'{ROOT}/test', exist_ok=True)
    with open(f'{ROOT}/test/mis_result.txt', 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
