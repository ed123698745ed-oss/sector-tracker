"""依題材分類表與上榜規則，從 data/quotes 計算每日上榜題材，輸出 docs/data.json 給網頁使用。

上榜規則 V01（Ed 2026-10-19 確認，B 條件同日依案例修正），符合任一條即上榜：
  A 齊漲：漲幅 ≥3% 的成分股 ≥3 檔，且佔當日有成交成分股 ≥25%
  B 帶頭擴散：漲幅 ≥4% 的 ≥2 檔，且漲幅 ≥1.5% 的家數佔有成交成分股 ≥40%
  C 強勢：漲幅 ≥7% 的 ≥2 檔
當日無成交的成分股不計入家數。
規則 V02（Ed 2026-10-21 確認）：2015-06-01 前漲跌幅限制為 7%，該期間收盤鎖漲停者視同漲幅 ≥7%（僅影響 C 條件）。
"""
import datetime, glob, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULE_VERSION = 'V02'
THEMES_VERSION = 'V12_20261021'
R = dict(A_pct=3.0, A_n=3, A_ratio=0.25, B_pct=4.0, B_n=2, B_follow_pct=1.5, B_follow=0.40, C_pct=7.0, C_n=2)
RECENT = 260  # 首頁載入的近期交易日數，其餘放 history.json
BASE_DAYS = 735  # 擴散基準：近三年交易日數（約 245 日 × 3）
LIMIT7_END = '20150601'  # 此日前漲跌幅限制為 7%
NEW_LISTING_DAYS = 5  # 新上市（櫃）前五個交易日無漲跌幅限制，不計入


def judge(p):
    n = len(p)
    if not n:
        return ''
    hit = ''
    a = sum(x >= R['A_pct'] for x in p)
    if a >= R['A_n'] and a / n >= R['A_ratio']:
        hit += 'A'
    if sum(x >= R['B_pct'] for x in p) >= R['B_n'] and sum(x >= R['B_follow_pct'] for x in p) / n >= R['B_follow']:
        hit += 'B'
    if sum(x >= R['C_pct'] for x in p) >= R['C_n']:
        hit += 'C'
    return hit


def load_themes():
    th = {}
    for i, line in enumerate(open(f'{ROOT}/config/themes.csv', encoding='utf-8')):
        if i == 0 or not line.strip():
            continue
        t, c, n = line.rstrip('\n').split(',')[:3]
        th.setdefault(t.strip(), []).append((c.strip(), n.strip()))
    return th


def load_groups(names):
    g = {}
    fp = f'{ROOT}/config/theme_groups.csv'
    if os.path.exists(fp):
        for i, line in enumerate(open(fp, encoding='utf-8')):
            if i and line.strip():
                t, c = line.rstrip('\n').split(',')[:2]
                g[t.strip()] = c.strip()
    for t in names:
        if t not in g:
            print('WARNING 題材未分類（列入傳產）:', t)
    return [g.get(t, '傳產') for t in names]


def market_caps(th):
    """各題材成分股市值總和（億元）：最近一日收盤價 × 發行股數。
    上市股數取自 config/shares.json（證交所公司基本資料），上櫃股數取自櫃買每日收盤行情的「發行股數」欄。"""
    import gzip
    num = lambda x: float(str(x).replace(',', '').strip()) if str(x).replace(',', '').strip().replace('.', '', 1).isdigit() else None
    cap = {}
    sp = f'{ROOT}/config/shares.json'
    shares = json.load(open(sp)) if os.path.exists(sp) else {}
    tws = sorted(glob.glob(f'{ROOT}/archive/raw/twse/*.json.gz'))
    if tws and shares:
        for t in json.load(gzip.open(tws[-1], 'rt')).get('tables', []):
            if '每日收盤行情' in (t.get('title') or ''):
                f = t['fields']; ic = f.index('收盤價')
                for r in t['data']:
                    c, px = r[0], num(r[ic])
                    if px and c in shares:
                        cap[c] = px * shares[c] / 1e8
    tps = sorted(glob.glob(f'{ROOT}/archive/raw/tpex/*.json.gz'))
    if tps:
        for t in json.load(gzip.open(tps[-1], 'rt')).get('tables', []):
            f = [x.strip() for x in t.get('fields', [])]
            if '發行股數' in f and '收盤' in f:
                ic, isd = f.index('收盤'), f.index('發行股數')
                for r in t['data']:
                    px, sh = num(r[ic]), num(r[isd])
                    if px and sh:
                        cap[r[0]] = px * sh / 1e8
    return {t: round(sum(cap.get(c, 0) for c, _ in m)) for t, m in th.items()}


def load_periods():
    """題材有效期間（config/theme_periods.csv）：期間外不判斷上榜、不列入題材數。"""
    per = {}
    fp = f'{ROOT}/config/theme_periods.csv'
    if os.path.exists(fp):
        for i, line in enumerate(open(fp, encoding='utf-8')):
            if i and line.strip():
                t, a, b = (line.rstrip('\n').split(',') + ['', ''])[:3]
                per[t.strip()] = (a.strip().replace('-', ''), b.strip().replace('-', ''))
    return per


def main():
    th = load_themes()
    per = load_periods()
    names = list(th)
    groups = load_groups(names)
    days = []
    seen = {}  # 代號 → 第幾個交易日首次出現（用來排除新上市前五日：無漲跌幅限制）
    for k, fp in enumerate(sorted(glob.glob(f'{ROOT}/data/quotes/*.json'))):
        d = json.load(open(fp))
        q = d['q']
        for c in q:
            seen.setdefault(c, k)
        q = {c: v for c, v in q.items() if seen[c] == 0 or k - seen[c] >= NEW_LISTING_DAYS}
        rows = []
        for t in names:
            a, b = per.get(t, ('', ''))
            if (a and d['date'] < a) or (b and d['date'] > b):
                rows.append([])  # 有效期間外
                continue
            mem = [(n, q[c][0]) for c, n in th[t] if c in q]
            p = [x for _, x in mem]
            if d['date'] < LIMIT7_END:  # 漲跌幅 7% 時期：鎖漲停視同達 C 條件的 7%（規則 V02）
                hit = judge([max(q[c][0], R['C_pct']) if len(q[c]) > 2 and q[c][2] else q[c][0] for c, _ in th[t] if c in q])
            else:
                hit = judge(p)
            avg = round(sum(p) / len(p), 2) if p else None
            row = [hit, avg, sum(x >= 3 for x in p), len(p), sum(q[c][2] if len(q[c]) > 2 else 0 for c, _ in th[t] if c in q)]
            if hit:  # 上榜題材附全部有成交成分股（依漲幅排序）
                row.append([[n, x] for n, x in sorted(mem, key=lambda z: -z[1])])
            rows.append(row)
        days.append({'d': d['date'], 'tx': d['taiex'], 't': rows})
    # 各大盤漲跌區間的平均上榜數（全部歷史）
    def bucket(x):
        return None if x is None else 0 if x <= -2 else 1 if x <= -1 else 2 if x < 0 else 3 if x < 1 else 4 if x < 2 else 5
    bs, bc = [0] * 6, [0] * 6
    for d in days:
        b = bucket(d['tx'])
        if b is not None:
            bs[b] += sum(1 for r in d['t'] if r and r[0]); bc[b] += 1
    # 每日基準：近三年（含當日往前 BASE_DAYS 個交易日）大盤漲跌落在同一區間的平均上榜數
    from collections import deque
    win, ws, wc = deque(), [0] * 6, [0] * 6
    for d in days:
        b = bucket(d['tx'])
        h = sum(1 for r in d['t'] if r and r[0])
        win.append((b, h))
        if b is not None:
            ws[b] += h; wc[b] += 1
        if len(win) > BASE_DAYS:
            ob, oh = win.popleft()
            if ob is not None:
                ws[ob] -= oh; wc[ob] -= 1
        d['ba'] = round(ws[b] / wc[b], 1) if b is not None and wc[b] else None
    recent, hist = days[-RECENT:], days[:-RECENT]
    meta = {
        'generated': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M'),
        'rule_version': RULE_VERSION, 'themes_version': THEMES_VERSION, 'rule': R,
        'themes': names, 'groups': groups, 'periods': {t: list(v) for t, v in per.items()}, 'mcap': market_caps(th), 'members': {t: [n for _, n in th[t]] for t in names},
        'bucket_avg': [round(s / c, 2) if c else None for s, c in zip(bs, bc)], 'bucket_n': bc,
        'first_day': days[0]['d'], 'hist_dates': [d['d'] for d in hist],
    }
    os.makedirs(f'{ROOT}/docs', exist_ok=True)
    dump = lambda o, f: json.dump(o, open(f'{ROOT}/docs/{f}', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    dump({'meta': meta, 'days': recent}, 'data.json')
    dump({'days': hist}, 'history.json')
    last = days[-1]
    print('days', len(days), 'last', last['d'], 'hits', sum(1 for r in last['t'] if r and r[0]))


if __name__ == '__main__':
    main()
