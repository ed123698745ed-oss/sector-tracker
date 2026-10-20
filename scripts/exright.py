"""證交所除權除息計算結果表（TWT49U）：取得上市股票除權息日的參考價，存 data/exright_twse.json（日期 → {代號: 參考價}）。

  python3 exright.py range 2015-01 2026-10   逐月抓取補齊
  python3 exright.py day YYYYMMDD           只抓單日（每日更新用）
"""
import datetime, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quotes  # noqa: E402

FP = os.path.join(quotes.ROOT, 'data', 'exright_twse.json')


def load():
    return json.load(open(FP)) if os.path.exists(FP) else {}


def fetch(a, b):
    d = quotes.get_json(f'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={a}&endDate={b}&response=json')
    out = {}
    if d.get('stat') != 'OK':
        return out
    f = d['fields']
    i_d, i_c, i_r = f.index('資料日期'), f.index('股票代號'), f.index('除權息參考價')
    for r in d.get('data', []):
        y, m, dd = [int(x) for x in r[i_d].replace('年', ' ').replace('月', ' ').replace('日', '').split()]
        ds = f'{y + 1911}{m:02d}{dd:02d}'
        ref = quotes.num(r[i_r])
        if ref:
            out.setdefault(ds, {})[r[i_c].strip()] = ref
    return out


def fetch_reduction(a, b):
    """減資恢復買賣參考價（TWTAUU）"""
    d = quotes.get_json(f'https://www.twse.com.tw/rwd/zh/reducation/TWTAUU?startDate={a}&endDate={b}&response=json')
    out = {}
    if d.get('stat') != 'OK':
        return out
    f = d['fields']
    i_d, i_c, i_r = f.index('恢復買賣日期'), f.index('股票代號'), f.index('恢復買賣參考價')
    for r in d.get('data', []):
        y, m, dd = [int(x) for x in r[i_d].split('/')]
        ref = quotes.num(r[i_r])
        if ref:
            out.setdefault(f'{y + 1911}{m:02d}{dd:02d}', {})[r[i_c].strip()] = ref
    return out


def merge(data, new):
    for k, v in new.items():
        data.setdefault(k, {}).update(v)


def save(data):
    json.dump(data, open(FP, 'w'), separators=(',', ':'), sort_keys=True)


MODE = ''

if __name__ == '__main__':
    data = load()
    if len(sys.argv) > 4:
        MODE = sys.argv[4]
    if sys.argv[1] == 'day':
        ds = sys.argv[2]
        merge(data, fetch(ds, ds)); merge(data, fetch_reduction(ds, ds)); save(data)
    else:
        y, m = map(int, sys.argv[2].split('-')); y2, m2 = map(int, sys.argv[3].split('-'))
        while (y, m) <= (y2, m2):
            a = datetime.date(y, m, 1); b = (a + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
            got = {} if MODE == 'reduction' else fetch(a.strftime('%Y%m%d'), b.strftime('%Y%m%d'))
            merge(data, got)
            time.sleep(2)
            red = fetch_reduction(a.strftime('%Y%m%d'), b.strftime('%Y%m%d'))
            merge(data, red); save(data)
            got = {**got, **red}
            print(a.strftime('%Y-%m'), sum(len(v) for v in got.values()), flush=True)
            time.sleep(3)
            m += 1
            if m > 12: y, m = y + 1, 1
