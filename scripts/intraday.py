"""盤中快照（測試版）：從證交所「基本市況報導」查詢題材成分股的最新成交價，計算盤中上榜題材。

  python3 intraday.py   抓一次，輸出盤中暫定結果到 docs/intraday.json，抓取統計附記到 test/mis_result.txt
  intraday.json：date、time、quote_time、active、tx（加權漲跌%）、hits＝[題材, 規則, 均漲, ≥3%家數, 有成交家數,
  [[名稱, 漲跌%]…（依漲幅排序）], 漲停家數]；只存上榜題材的成分股，供網頁盤中顯示摘要與熱門題材卡片
  all＝[題材, 均漲, ≥3%家數, 有成交家數, 漲停家數]，全部有效題材（含未上榜），供全部題材表、熱度圖、熱門題材數盤中顯示
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
    th, names = {}, {}
    for r in list(csv.reader(open(f'{ROOT}/config/themes.csv', encoding='utf-8')))[1:]:
        a, b = per.get(r[0], ('', ''))
        if (a and today < a) or (b and today > b):  # 已過有效期間的題材不判斷
            continue
        th.setdefault(r[0], []).append(r[1])
        names[r[1]] = r[2] if len(r) > 2 else r[1]
    return th, names


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


def price(x):
    """pct() 採用的價格（成交價，無成交時用最佳買／賣價）；取不到回 None"""
    z = x.get('z', '-')
    try:
        if z not in ('-', '', None) and float(z) > 0:
            return float(z)
    except ValueError:
        pass
    for k in ('b', 'a'):
        for v in (x.get(k) or '').split('_'):
            try:
                if float(v) > 0:
                    return float(v)
            except ValueError:
                pass
    return None


def at_limit_up(x):
    try:
        u, z = float(x.get('u') or 0), price(x)
        return bool(u and z and z >= u - 1e-6)
    except ValueError:
        return False


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
            z = None
            for k in ('b', 'a'):  # 各檔價位中第一個大於 0 的價格（無掛單時證交所會給 0 或 -）
                for v in (x.get(k) or '').split('_'):
                    try:
                        if float(v) > 0:
                            z = float(v); break
                    except ValueError:
                        pass
                if z:
                    break
            if not z:
                return None
        r = round((float(z) - y) / y * 100, 2)
        return r if abs(r) <= 10.5 else None  # 超出漲跌幅限制視為異常值（新上市蜜月期亦不計）
    except Exception:
        return None


def main():
    th, names = members()
    codes = sorted({c for v in th.values() for c in v})
    t0 = time.time()
    q, stat = fetch(codes, market_of())
    tx = None
    try:  # 加權指數
        ix, _ = fetch(['t00'], {'t00'})
        tx = pct(ix['t00']) if 't00' in ix else None
    except Exception:
        pass
    secs = round(time.time() - t0, 1)
    p = {c: pct(x) for c, x in q.items()}
    got = sum(v is not None for v in p.values())
    hits, rows, allr = [], [], []
    for t, cs in th.items():
        pp = [p[c] for c in cs if p.get(c) is not None]
        h = judge(pp)
        allr.append([t, round(sum(pp) / len(pp), 2) if pp else None, sum(x >= 3 for x in pp), len(pp),
                     sum(1 for c in cs if p.get(c) is not None and at_limit_up(q[c]))])
        if h:
            hits.append(f'{t}({h})')
            mem = sorted(([names.get(c, c), p[c]] for c in cs if p.get(c) is not None), key=lambda z: -z[1])
            lu = sum(1 for c in cs if p.get(c) is not None and at_limit_up(q[c]))
            rows.append([t, h, round(sum(pp) / len(pp), 2), sum(x >= 3 for x in pp), len(pp), mem, lu])
    rows.sort(key=lambda r: -r[2])
    times = sorted({x.get('t') for x in q.values() if x.get('t')})
    lines = [
        f"run_at {datetime.datetime.now(TPE).strftime('%Y-%m-%d %H:%M:%S')}",
        f"codes {len(codes)} returned {len(q)} priced {got} seconds {secs}",
        f"requests {stat['requests']} errors {stat['errors']} last_error {stat.get('last_error','')}",
        f"quote_time_range {times[:1]} {times[-1:]}",
        f"hits {len(hits)} {' '.join(hits)}",
    ]
    now = datetime.datetime.now(TPE)
    out = {'date': now.strftime('%Y%m%d'), 'time': now.strftime('%H:%M'),
           'quote_time': times[-1] if times else None, 'active': len(th), 'tx': tx, 'priced': got, 'total': len(codes), 'hits': rows, 'all': allr}
    json.dump(out, open(f'{ROOT}/docs/intraday.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    os.makedirs(f'{ROOT}/test', exist_ok=True)
    with open(f'{ROOT}/test/mis_result.txt', 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
