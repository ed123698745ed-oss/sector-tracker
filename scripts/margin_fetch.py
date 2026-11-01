"""抓取證交所、櫃買中心每日融資融券餘額原始檔（融資觀察分頁用）。

  python3 margin_fetch.py run YYYYMMDD[,YYYYMMDD…]   逐日抓取，原始檔存 archive/raw/twse_margin、tpex_margin
  python3 margin_fetch.py list START IDX N            回補接力用：缺日輪流分給 N 個工作，印出第 IDX 個的日期
  python3 margin_fetch.py backfill START [END]        抓 START～END 間已有收盤精簡檔（data/quotes）的交易日中缺的日子

來源：
  上市 https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=YYYYMMDD&selectType=ALL&response=json
       （「信用交易統計」表：融資金額(仟元)；「融資融券彙總」表：個股融資買進／賣出／現金償還／前日餘額／今日餘額／次一營業日限額，單位張）
  上櫃 https://www.tpex.org.tw/www/zh-tw/margin/balance?date=YYYY/MM/DD&response=json
       （個股前資餘額／資買／資賣／現償／資餘額／資使用率／資限額，單位張；表尾「融資金(仟元)」為上櫃融資金額）

防錯（Emit 防錯清單）：
  - 日期以回應內文的資料日為準，與要求日不符（休市日回前一日資料）就不存檔（A1）
  - 回應 2xx 但不是 JSON、stat 不是 OK、個股列數過少或比前一份少一成以上，都視為失敗（B 補充、B2）
  - 上市、上櫃分開存，一邊失敗不影響另一邊（B 補充）
"""
import datetime, gzip, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'archive', 'raw')
UA = {'User-Agent': 'Mozilla/5.0 (sector-tracker margin)'}
MIN_ROWS = {'twse': 600, 'tpex': 400}  # 低於此列數視為不完整（2025～2026 上市約 1,300、上櫃約 900 列）


def get_json(url):
    last = None
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                body = r.read()
                try:
                    return json.loads(body)
                except ValueError:  # 2xx 但不是 JSON（B 補充）
                    last = f'非 JSON：status={r.status} type={r.headers.get("Content-Type")} body={body[:200]!r}'
                    print('retry', i, last, flush=True)
        except Exception as e:
            last = repr(e)
            print('retry', i, last, flush=True)
        time.sleep(10 * (i + 1))
    raise RuntimeError(f'抓取失敗：{url}｜{last}')


def roc_to_ds(s):
    """'115年10月30日' 或 '115/10/30' → '20261030'"""
    m = re.search(r'(\d{2,3})\D+(\d{1,2})\D+(\d{1,2})', s or '')
    if not m:
        return None
    return f'{int(m.group(1)) + 1911:04d}{int(m.group(2)):02d}{int(m.group(3)):02d}'


def check_twse(j, ds):
    if j.get('stat') != 'OK':
        return f'stat={j.get("stat")}'
    tabs = j.get('tables') or []
    summ = next((t for t in tabs if '信用交易統計' in (t.get('title') or '')), None)
    det = next((t for t in tabs if '融資融券彙總' in (t.get('title') or '')), None)
    if not summ or not det:
        return '缺表'
    got = roc_to_ds(summ.get('title'))
    if got != ds:
        return f'資料日 {got} 與要求日 {ds} 不符'
    if len(det.get('data') or []) < MIN_ROWS['twse']:
        return f'個股列數過少 {len(det.get("data") or [])}'
    return None


def check_tpex(j, ds):
    tabs = j.get('tables') or []
    t = tabs[0] if tabs else {}
    got = roc_to_ds(t.get('date') or j.get('date') or '')
    if got != ds:
        return f'資料日 {got} 與要求日 {ds} 不符'
    if len(t.get('data') or []) < MIN_ROWS['tpex']:
        return f'個股列數過少 {len(t.get("data") or [])}'
    if not any('融資金' in str(r[1]) for r in (t.get('summary') or [])):
        return '缺融資金合計列'
    return None


def prev_rows(src, ds):
    """ds 之前最近一份同來源原始檔的個股列數（B2：與前一交易日相比大減就不存）"""
    d = os.path.join(RAW, src)
    if not os.path.isdir(d):
        return None
    prev = sorted(f for f in os.listdir(d) if f[:8] < ds)
    if not prev:
        return None
    with gzip.open(os.path.join(d, prev[-1]), 'rt', encoding='utf-8') as f:
        j = json.load(f)
    tabs = j.get('tables') or []
    t = next((t for t in tabs if '融資融券彙總' in (t.get('title') or '')), None) if src == 'twse_margin' else (tabs[0] if tabs else None)
    return len((t or {}).get('data') or [])


def count_ok(src, ds, n):
    p = prev_rows(src, ds)
    return p is None or n >= p * 0.9


def save(src, ds, obj):
    d = os.path.join(RAW, src)
    os.makedirs(d, exist_ok=True)
    with gzip.open(os.path.join(d, f'{ds}.json.gz'), 'wt', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))


def have(src, ds):
    return os.path.exists(os.path.join(RAW, src, f'{ds}.json.gz'))


def fetch_one(ds, sleep=4):
    """回傳 {'twse': 'ok'|錯誤訊息, 'tpex': …}；已存在就跳過"""
    res = {}
    d = datetime.date(int(ds[:4]), int(ds[4:6]), int(ds[6:]))
    if have('twse_margin', ds):
        res['twse'] = 'ok(已有)'
    else:
        try:
            j = get_json(f'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ds}&selectType=ALL&response=json')
            err = check_twse(j, ds)
            if not err:
                n = len(next(t for t in j['tables'] if '融資融券彙總' in (t.get('title') or ''))['data'])
                if not count_ok('twse_margin', ds, n):
                    err = f'個股列數 {n} 比前一份少一成以上'
            if err:
                res['twse'] = err
            else:
                save('twse_margin', ds, j); res['twse'] = 'ok'
        except Exception as e:
            res['twse'] = str(e)[:200]
        time.sleep(sleep)
    if have('tpex_margin', ds):
        res['tpex'] = 'ok(已有)'
    else:
        try:
            j = get_json(f'https://www.tpex.org.tw/www/zh-tw/margin/balance?date={d.year}%2F{d.month:02d}%2F{d.day:02d}&response=json')
            err = check_tpex(j, ds)
            if not err and not count_ok('tpex_margin', ds, len(j['tables'][0]['data'])):
                err = f'個股列數 {len(j["tables"][0]["data"])} 比前一份少一成以上'
            if err:
                res['tpex'] = err
            else:
                save('tpex_margin', ds, j); res['tpex'] = 'ok'
        except Exception as e:
            res['tpex'] = str(e)[:200]
        time.sleep(sleep)
    return res


def run(dates):
    bad = 0
    for ds in dates:
        r = fetch_one(ds)
        print(ds, r, flush=True)
        bad += sum(1 for v in r.values() if not v.startswith('ok'))
    return bad


def missing(start, end=None):
    end = end or '99999999'
    qd = os.path.join(ROOT, 'data', 'quotes')
    days = sorted(f[:8] for f in os.listdir(qd) if f.endswith('.json') and start <= f[:8] <= end)
    return [d for d in reversed(days) if not (have('twse_margin', d) and have('tpex_margin', d))]  # 由新到舊


def backfill(start, end=None):
    todo = missing(start, end)
    print(f'待抓 {len(todo)} 天', flush=True)
    return run(todo)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'run':
        sys.exit(1 if run(sys.argv[2].split(',')) else 0)
    elif cmd == 'list':  # list START IDX N：缺日依序輪流分給 N 個工作，印出第 IDX 個工作的日期
        idx, n = int(sys.argv[3]), int(sys.argv[4])
        print(','.join(missing(sys.argv[2])[idx::n]))
    elif cmd == 'backfill':
        backfill(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print(__doc__)
