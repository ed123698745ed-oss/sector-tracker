"""抓取並解析證交所、櫃買中心每日收盤行情，存成精簡檔 data/quotes/YYYYMMDD.json。

精簡檔格式：{"date": "YYYYMMDD", "taiex": 加權漲跌%, "q": {代號: [漲跌%, 成交金額(億)]}}
漲跌% = 漲跌價差 ÷ (收盤 − 漲跌價差) × 100，即對前一交易日參考價；無成交或不比價者不列入。
除權息日：上市以證交所除權除息計算結果表（TWT49U）的除權息參考價計算；上櫃以前一交易日公布的
次日漲停價與跌停價推算參考價（兩者平均）。
前一交易日無成交（多為暫停交易後恢復）證交所也標 X：對最近一次收盤計算；期間有除權息／減資，或算出超過漲跌幅限制
（面額分割、變更面額等另行調整參考價）則不推算、維持排除。

用法：
  python3 quotes.py fetch [YYYY-MM-DD]      抓一天（預設今天台北時間）；休市日不產生檔案
  python3 quotes.py convert <raw_dir>       把既有原始 JSON（raw/twse、raw/tpex）轉成精簡檔
"""
import datetime, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'quotes')
UA = {'User-Agent': 'Mozilla/5.0 (sector-tracker)'}


LIMIT_CHANGE = '20150601'  # 漲跌幅限制由 7% 放寬為 10%


def tick(p):
    return 0.01 if p < 10 else 0.05 if p < 50 else 0.1 if p < 100 else 0.5 if p < 500 else 1 if p < 1000 else 5


def limit_up(ref, ds):
    """依參考價與升降單位計算漲停價（向下取至該價位的升降單位）"""
    lim = ref * (1.07 if ds < LIMIT_CHANGE else 1.10)
    t = tick(lim)
    v = int(lim / t + 1e-9) * t
    if tick(v) != t:  # 跨價位級距時以較低級距重算
        t = tick(v); v = int(lim / t + 1e-9) * t
    return round(v, 2)


def is_lu(close, ref, ds):
    return 1 if close and ref and close >= limit_up(ref, ds) - 1e-6 else 0


def num(s):
    try:
        return float(str(s).replace(',', '').replace(' ', '').strip())
    except ValueError:
        return None


def parse_twse(d, exref=None, ds='99999999', lastclose=None, exall=None):
    q, taiex = {}, None
    exref = exref or {}
    lastclose = lastclose or {}
    for t in d.get('tables', []):
        title = t.get('title') or ''
        if title.endswith('價格指數(臺灣證券交易所)'):
            for r in t['data']:
                if r[0] in ('發行量加權股價指數', '加權股價指數'):
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
                code = r[0].strip()
                if sg == 'X' and close and exref.get(code):  # 除權息／減資恢復買賣日：對參考價
                    ref = exref[code]
                    q[code] = [round((close - ref) / ref * 100, 2), round((num(r[iv]) or 0) / 1e8, 2), is_lu(close, ref, ds)]
                    continue
                if sg == 'X' and close and code in lastclose:  # 前一交易日無成交（多為暫停交易後恢復）：對最近一次收盤
                    d0, ref = lastclose[code]
                    lim = 7.5 if ds < LIMIT_CHANGE else 10.5  # 超過漲跌幅限制＝參考價另有調整（面額分割、變更面額等），不推算
                    if ref and abs(close / ref - 1) * 100 <= lim and \
                            not any(code in (exall or {}).get(x, {}) for x in (exall or {}) if d0 < x <= ds):
                        q[code] = [round((close - ref) / ref * 100, 2), round((num(r[iv]) or 0) / 1e8, 2), is_lu(close, ref, ds)]
                    continue
                if close is None or diff is None or sg not in ('+', '-', ''):
                    continue
                diff = -diff if sg == '-' else diff
                prev = close - diff
                if prev > 0:
                    q[code] = [round(diff / prev * 100, 2), round((num(r[iv]) or 0) / 1e8, 2), is_lu(close, prev, ds)]
    return q, taiex


def tpex_limits(d, want_up=False):
    """上櫃前一交易日公布的次日漲跌停價 → {代號: 推算參考價}（want_up=True 時回傳次日漲停價）"""
    out = {}
    for t in (d or {}).get('tables', []):
        f = [x.strip() for x in t.get('fields', [])]
        if '次日漲停價' not in f:
            continue
        iu, idn = f.index('次日漲停價'), f.index('次日跌停價')
        for r in t['data']:
            up, dn = num(r[iu]), num(r[idn])
            if up and dn and abs(up - 9999.95) > 1e-6:  # 9999.95＝無漲跌幅限制（債券 ETF 等）的代表值；股價破萬（信驊）照算
                out[r[0].strip()] = up if want_up else (up + dn) / 2
    return out


def parse_tpex(d, prevraw=None, ds='99999999'):
    q = {}
    refs = None
    ups = tpex_limits(prevraw, True) if prevraw else {}
    for t in d.get('tables', []):
        f = [x.strip() for x in t.get('fields', [])]
        if '收盤' not in f:
            continue
        ic, idf, iv = f.index('收盤'), f.index('漲跌'), f.index('成交金額(元)')
        for r in t['data']:
            close, diff = num(r[ic]), num(r[idf])
            code = r[0].strip()
            if close and diff is None and '除' in str(r[idf]):  # 除權／除息／除權息
                if refs is None:
                    refs = tpex_limits(prevraw)
                ref = refs.get(code)
                if ref:
                    lu = 1 if code in ups and close >= ups[code] - 1e-6 else is_lu(close, ref, ds)
                    q[code] = [round((close - ref) / ref * 100, 2), round((num(r[iv]) or 0) / 1e8, 2), lu]
                continue
            if close is None or diff is None:
                continue
            prev = close - diff
            if prev > 0:
                lu = 1 if code in ups and close >= ups[code] - 1e-6 else is_lu(close, prev, ds)
                q[code] = [round(diff / prev * 100, 2), round((num(r[iv]) or 0) / 1e8, 2), lu]
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


def has_twse_exright(tw):
    for t in tw.get('tables', []):
        if '每日收盤行情' in (t.get('title') or ''):
            isg = t['fields'].index('漲跌(+/-)')
            return any('X' in str(r[isg]) for r in t['data'])
    return False


def twse_closes(d):
    """上市原始檔 → {代號: 收盤}（只含有成交的）"""
    out = {}
    for t in (d or {}).get('tables', []):
        if '每日收盤行情' in (t.get('title') or ''):
            ic = t['fields'].index('收盤價')
            for r in t['data']:
                c = num(r[ic])
                if c:
                    out[r[0].strip()] = c
    return out


def x_codes(tw):
    """上市原始檔中標 X（不比價）且有收盤的代號"""
    out = set()
    for t in (tw or {}).get('tables', []):
        if '每日收盤行情' in (t.get('title') or ''):
            f = t['fields']
            ic, isg = f.index('收盤價'), f.index('漲跌(+/-)')
            for r in t['data']:
                if re.sub('<[^>]+>', '', r[isg]).strip() == 'X' and num(r[ic]):
                    out.add(r[0].strip())
    return out


def last_twse_closes(ds, codes, maxback=260):
    """ds 之前各代號最近一次收盤 {代號: (日期, 收盤)}；往回最多 maxback 個原始檔（約一年）"""
    import glob, gzip
    need, out = set(codes), {}
    for f in sorted(glob.glob(f'{ROOT}/archive/raw/twse/*.json.gz'), reverse=True):
        d8 = os.path.basename(f)[:8]
        if d8 >= ds:
            continue
        if not need or maxback <= 0:
            break
        maxback -= 1
        cl = twse_closes(json.load(gzip.open(f, 'rt')))
        for c in list(need):
            if c in cl:
                out[c] = (d8, cl[c]); need.discard(c)
    return out


def prev_tpex_raw(ds):
    """archive/raw/tpex 中 ds 之前最近一個有資料的交易日原始檔"""
    import glob, gzip
    for f in sorted(glob.glob(f'{ROOT}/archive/raw/tpex/*.json.gz'), reverse=True):
        if os.path.basename(f)[:8] < ds:
            d = json.load(gzip.open(f, 'rt'))
            if parse_tpex(d):
                return d
    return None


def is_holiday(day):
    """依證交所休市日期表判斷是否為公告休市日（含「X月X日至X月X日」區間與補假）。"""
    d = get_json(f'https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?date={day.year}0101&response=json')
    days = set()
    for r in d.get('data', []):
        date, name, note = r[0], r[1] or '', r[2] or ''
        if '交易日' not in name:
            days.add(date)
        for m1, d1, m2, d2 in re.findall(r'(\d+)月(\d+)日至(\d+)月(\d+)日', note):
            a = datetime.date(day.year, int(m1), int(d1)); b = datetime.date(day.year, int(m2), int(d2))
            while a <= b:
                days.add(a.isoformat()); a += datetime.timedelta(days=1)
        for m1, d1 in re.findall(r'於(\d+)月(\d+)日[^補]{0,8}補', note):
            days.add(datetime.date(day.year, int(m1), int(d1)).isoformat())
    return day.isoformat() in days


def save(ds, tw, tp, exref=None, prevtp=None, lastclose=None, exall=None):
    q, taiex = parse_twse(tw, exref, ds, lastclose, exall)
    if not q:
        return False  # 休市
    if not tp or not parse_tpex(tp):
        raise SystemExit(f'{ds} 上市有資料但上櫃無資料，停止，不產生不完整檔案')
    q.update(parse_tpex(tp, prevtp, ds))
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
    elif cmd == 'rebuild':  # 由 archive/raw 全部重算精簡檔（含除權息日）
        import glob, gzip
        ex = json.load(open(f'{ROOT}/data/exright_twse.json'))
        prev, n, last = None, 0, {}
        for f in sorted(glob.glob(f'{ROOT}/archive/raw/twse/*.json.gz')):
            ds = os.path.basename(f)[:8]
            tw = json.load(gzip.open(f, 'rt'))
            xs = x_codes(tw)
            lc = {c: last[c] for c in xs if c in last}
            tpp = f'{ROOT}/archive/raw/tpex/{ds}.json.gz'
            tp = json.load(gzip.open(tpp, 'rt')) if os.path.exists(tpp) else None
            if save(ds, tw, tp, ex.get(ds), prev, lc, ex):
                n += 1
                prev = tp
                last.update({c: (ds, v) for c, v in twse_closes(tw).items()})
        print('rebuilt', n)
    elif cmd == 'convert':
        raw = sys.argv[2]
        n = 0
        for f in sorted(os.listdir(f'{raw}/twse')):
            tw = json.load(open(f'{raw}/twse/{f}'))
            tpp = f'{raw}/tpex/{f}'
            tp = json.load(open(tpp)) if os.path.exists(tpp) else None
            n += save(f[:8], tw, tp)
        print('converted', n)
