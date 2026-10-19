"""依題材分類表與上榜規則，從 data/quotes 計算每日上榜題材，輸出 docs/data.json 給網頁使用。

上榜規則 V01（Ed 2026-10-19 確認，B 條件同日依案例修正），符合任一條即上榜：
  A 齊漲：漲幅 ≥3% 的成分股 ≥3 檔，且佔當日有成交成分股 ≥25%
  B 帶頭擴散：漲幅 ≥4% 的 ≥2 檔，且漲幅 ≥1.5% 的家數佔有成交成分股 ≥40%
  C 強勢：漲幅 ≥7% 的 ≥2 檔
當日無成交的成分股不計入家數。
"""
import datetime, glob, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULE_VERSION = 'V01'
THEMES_VERSION = 'V04_20261020'
R = dict(A_pct=3.0, A_n=3, A_ratio=0.25, B_pct=4.0, B_n=2, B_follow_pct=1.5, B_follow=0.40, C_pct=7.0, C_n=2)
LIMIT = 9.5  # 視為漲停的近似門檻
RECENT = 260  # 首頁載入的近期交易日數，其餘放 history.json


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


def main():
    th = load_themes()
    names = list(th)
    days = []
    for fp in sorted(glob.glob(f'{ROOT}/data/quotes/*.json')):
        d = json.load(open(fp))
        q = d['q']
        rows = []
        for t in names:
            mem = [(n, q[c][0]) for c, n in th[t] if c in q]
            p = [x for _, x in mem]
            hit = judge(p)
            avg = round(sum(p) / len(p), 2) if p else None
            row = [hit, avg, sum(x >= 3 for x in p), len(p), sum(x >= LIMIT for x in p)]
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
            bs[b] += sum(1 for r in d['t'] if r[0]); bc[b] += 1
    recent, hist = days[-RECENT:], days[:-RECENT]
    meta = {
        'generated': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M'),
        'rule_version': RULE_VERSION, 'themes_version': THEMES_VERSION, 'rule': R,
        'themes': names, 'members': {t: [n for _, n in th[t]] for t in names},
        'bucket_avg': [round(s / c, 2) if c else None for s, c in zip(bs, bc)], 'bucket_n': bc,
        'first_day': days[0]['d'], 'hist_dates': [d['d'] for d in hist],
    }
    os.makedirs(f'{ROOT}/docs', exist_ok=True)
    dump = lambda o, f: json.dump(o, open(f'{ROOT}/docs/{f}', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    dump({'meta': meta, 'days': recent}, 'data.json')
    dump({'days': hist}, 'history.json')
    last = days[-1]
    print('days', len(days), 'last', last['d'], 'hits', sum(1 for r in last['t'] if r[0]))


if __name__ == '__main__':
    main()
