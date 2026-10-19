"""抓取並解析證交所、櫃買中心每日收盤行情，存成精簡檔 data/quotes/YYYYMMDD.json。

精簡檔格式：{"date": "YYYYMMDD", "taiex": 加權漲跌%, "q": {代號: [漲跌%, 成交金額(億)]}}
漲跌% = 漲跌價差 ÷ (收盤 − 漲跌價差) × 100，即對前一交易日參考價；無成交或不比價者不列入。

用法：
  python3 quotes.py fetch [YYYY-MM-DD]      抓一天（預設今天台北時間）；休市日不產生檔案
  python3 quotes.py convert <raw_dir>       把既有原始 JSON（raw/twse、raw/tpex）轉成精簡檔
"""
import datetime, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'quotes')
UA = {'User-Agent': 'Mozilla/5.0 (sector-tracker)'}


def num(s):
    try:
        return float(str(s).replace(',', '').strip())
    except ValueError:
        return None


def parse_twse(d):
    q, taiex = {}, None
    for t in d.get('tables', []):
        title = t.get('title') or ''
        if title.endswith('價格指數(臺灣證券交易所)'):
            for r in t['data']:
                if r[0] == '發行量加權股價指數':
                    sg = re.sub('<[^>]+>', '', r[2]).strip()
                    close, pts = num(r[1]), num(r[3])
                    if close is not None and pts is not None:
                        pts = -pts if sg == '-' else pts
                        taiex = round(pts / (close - pts) * 100, 2)
        if '每日收盤行情' in title:
            f = t['fields']
            ic, isg, idf, iv = f.index('收盤價'), f.index('漲跌(+/-)'), f.index('漲跌價差'), f.index('成交金額')
            for r in t['data']:
                close, diff = num(r[ic]), num(r[idf])
                sg = re.sub('<[^>]+>', '', r[isg]).strip()
                if close is None or diff is None or sg not in ('+', '-', ''):
                    continue
                diff = -diff if sg == '-' else diff
                prev = close - diff
                if prev > 0:
                    q[r[0].strip()] = [round(diff / prev * 100, 2), round((num(r[iv]) or 0) / 1e8, 2)]
    return q, taiex


def parse_tpex(d):
    q = {}
    for t in d.get('tables', []):
        f = [x.strip() for x in t.get('fields', [])]
        if '收盤' not in f:
            continue
        ic, idf, iv = f.index('收盤'), f.index('漲跌'), f.index('成交金額(元)')
        for r in t['data']:
            close, diff = num(r[ic]), num(r[idf])
            if close is None or diff is None:
                continue
            prev = close - diff
            if prev > 0:
                q[r[0].strip()] = [round(diff / prev * 100, 2), round((num(r[iv]) or 0) / 1e8, 2)]
    return q


def get_json(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read())
        except Exception as e:  # 連線重置等，退避重試
            print('retry', i, e, flush=True)
            time.sleep(15 * (i + 1))
    raise SystemExit(f'抓取失敗：{url}')


def save(ds, tw, tp):
    q, taiex = parse_twse(tw)
    if not q:
        return False  # 休市
    if not tp or not parse_tpex(tp):
        raise SystemExit(f'{ds} 上市有資料但上櫃無資料，停止，不產生不完整檔案')
    q.update(parse_tpex(tp))
    os.makedirs(OUT, exist_ok=True)
    json.dump({'date': ds, 'taiex': taiex, 'q': q}, open(f'{OUT}/{ds}.json', 'w'), separators=(',', ':'))
    return True


def fetch(day):
    ds = day.strftime('%Y%m%d')
    tw = get_json(f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ds}&type=ALLBUT0999&response=json')
    tp = get_json(f'https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={day.year}%2F{day.month:02d}%2F{day.day:02d}&type=EW&response=json')
    print(ds, 'saved' if save(ds, tw, tp) else 'holiday (no file)')


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'fetch':
        if len(sys.argv) > 2:
            day = datetime.date.fromisoformat(sys.argv[2])
        else:
            day = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))).date()
        fetch(day)
    elif cmd == 'convert':
        raw = sys.argv[2]
        n = 0
        for f in sorted(os.listdir(f'{raw}/twse')):
            tw = json.load(open(f'{raw}/twse/{f}'))
            tpp = f'{raw}/tpex/{f}'
            tp = json.load(open(tpp)) if os.path.exists(tpp) else None
            n += save(f[:8], tw, tp)
        print('converted', n)
