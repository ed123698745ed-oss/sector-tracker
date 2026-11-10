"""率先創新高觀察分頁：大盤低點後，哪些個股先突破低點前的高點。輸出 docs/newhigh.json。

只供觀察，不是交易訊號。規則由 Ed 2026-11-11 確認：
  - 錨點（大盤低點）：由 Ed 手動指定，記在 config/newhigh.json（預設 2026-11-06）。
  - 新高門檻：每檔股票在錨點日往前 250 個交易日（含錨點日）的最高「盤中最高價」，錨點日起凍結不再滾動。
  - 價格：盤中最高價（還原值，與權值與高價股頁同口徑）；錨點日之後第一個「盤中最高價嚴格高於門檻」的交易日＝創高日。
  - 不設流動性濾網：錨點日已上市的上市櫃普通股全部列入（排除 ETF、權證、特別股、TDR；同 wh_prices 口徑）。
  - 名次：依創高日先後，同日同名次；累積比例＝截至該日已創高檔數 ÷ 錨點日有效檔數。
  - 題材：config/themes.csv（錨點日仍有效的題材，theme_periods.csv）；「群聚」＝錨點後任一連續 5 個交易日內
    同題材有 3 檔以上首次創高。
  - 回看用的歷史錨點只追蹤錨點後 250 個交易日。

輸入：cache/wh_adj.npz（wh_build.py 產生）、cache/wh_px.json.gz（名稱、市場）、docs/wh.json（加權指數）、
      data/quotes（20 日均成交額）、config/newhigh.json、config/themes.csv、theme_groups.csv、theme_periods.csv
"""
import csv, gzip, json, os, sys, warnings

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN = 250        # 門檻回看交易日數（含錨點日）
TRACK = 250      # 歷史錨點的追蹤交易日數
NEAR = 5         # 接近創高：距門檻 5% 以內
CLU_D, CLU_N = 5, 3   # 群聚：5 個交易日內 3 檔


def load_themes(anchor):
    per = {}
    for r in csv.DictReader(open(os.path.join(ROOT, 'config', 'theme_periods.csv'), encoding='utf-8')):
        per[r['題材']] = (r['起始日'].replace('-', ''), r['結束日'].replace('-', ''))
    grp = {r['題材']: r['類別'] for r in csv.DictReader(open(os.path.join(ROOT, 'config', 'theme_groups.csv'), encoding='utf-8'))}
    th = {}
    for r in csv.DictReader(open(os.path.join(ROOT, 'config', 'themes.csv'), encoding='utf-8')):
        t = r['題材']; s, e = per.get(t, ('', ''))
        if (s and anchor < s) or (e and anchor > e):
            continue
        th.setdefault(t, []).append(r['代號'].strip())
    return th, grp


def avg_amount(dates_all, upto, n=20):
    """近 n 個交易日平均成交金額（億）：data/quotes 的成交金額欄，無成交日不計入分母"""
    ds = [d for d in dates_all if d <= upto][-n:]
    s, k = {}, {}
    for d in ds:
        q = json.load(open(os.path.join(ROOT, 'data', 'quotes', d + '.json')))['q']
        for c, v in q.items():
            if len(v) > 1 and v[1]:
                s[c] = s.get(c, 0) + v[1]; k[c] = k.get(c, 0) + 1
    return {c: round(s[c] / k[c], 2) for c in s}


def r2(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def build_anchor(a, D, codes, adj, adjH, close, pct, taiex, tdates, name, mkt, amt):
    dates = list(D)
    B = a['date']
    if B not in dates:
        raise SystemExit(f'錨點 {B} 不是資料內的交易日')
    tB = dates.index(B)
    T = len(dates)
    tEnd = T - 1 if a.get('current') else min(T - 1, tB + TRACK)
    w0 = max(0, tB - WIN + 1)
    if tB - WIN + 1 < 0:
        print(f'::warning::{B} 之前資料不足 {WIN} 日')
    listed = ~np.isnan(adj[tB])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        K = np.nanmax(adjH[w0:tB + 1], axis=0)
    hist = np.sum(~np.isnan(adj[w0:tB + 1]), axis=0)
    valid = listed & np.isfinite(K)
    idx = np.where(valid)[0]
    N = len(idx)
    # 首次創高日（錨點日之後）
    S = np.full(len(codes), -1)
    with np.errstate(invalid='ignore'):
        brk = adjH[tB + 1:tEnd + 1] > K * (1 + 1e-9)
    for k in idx:
        w = np.where(brk[:, k])[0]
        if len(w): S[k] = tB + 1 + w[0]
    broke = [k for k in idx if S[k] >= 0]
    broke.sort(key=lambda k: (S[k], codes[k]))
    # 名次與累積比例
    cnt_by_day = {}
    for k in broke: cnt_by_day[S[k]] = cnt_by_day.get(S[k], 0) + 1
    cum, rank_of_day, cum_of_day = 0, {}, {}
    for t in sorted(cnt_by_day):
        rank_of_day[t] = cum + 1; cum += cnt_by_day[t]; cum_of_day[t] = cum
    th, grp = load_themes(B)
    th_of = {}
    for t, cs in th.items():
        for c in cs: th_of.setdefault(c, []).append(t)
    tl = tEnd

    def stock_row(k):
        c = codes[k]
        a_l, a_b = adj[tl, k], adj[tB, k]
        return {'c': c, 'n': name.get(c, ''), 'm': 'o' if mkt.get(c) == 'tpex' else 't', 'th': th_of.get(c, []),
                'up': r2((a_l / a_b - 1) * 100 if a_b else None, 1),      # 自錨點收盤漲跌%
                'vk': r2((a_l / K[k] - 1) * 100, 1),                     # 最新收盤相對門檻%
                'pct': r2(pct[tl, k]), 'amt': amt.get(c) if a.get('current') else None,
                'px': r2(close[tl, k]), 'short': bool(hist[k] < WIN)}
    rows = []
    for k in broke:
        r = stock_row(k)
        r.update({'s': dates[S[k]], 'd': int(S[k] - tB), 'rk': rank_of_day[S[k]],
                  'cp': round(cum_of_day[S[k]] / N * 100, 1)})
        rows.append(r)
    # 尚未創高：盤中判斷用的未還原門檻＝門檻 × 最新未還原收盤 ÷ 最新還原收盤
    pend = []
    for k in idx:
        if S[k] >= 0: continue
        r = stock_row(k)
        f = close[tl, k] / adj[tl, k] if np.isfinite(close[tl, k]) and adj[tl, k] else None
        r['kr'] = r2(K[k] * f) if f else None
        if a.get('current') or (r['vk'] is not None and r['vk'] > -NEAR):
            pend.append(r)   # 歷史錨點只留接近創高者
    # 每日新增與累積
    days = []
    run = 0
    for t in range(tB, tEnd + 1):
        n_ = cnt_by_day.get(t, 0); run += n_
        days.append([dates[t], taiex.get(dates[t]), n_, run])
    # 加權：錨點前 250 日最高收盤
    tw = [taiex.get(d) for d in dates[w0:tB + 1] if taiex.get(d)]
    pre_hi = max(tw) if tw else None
    pre_hi_d = next((d for d in dates[w0:tB + 1] if taiex.get(d) == pre_hi), None)
    # 題材
    ci = {c: k for k, c in enumerate(codes)}
    themes = []
    for t, cs in th.items():
        mem = [c for c in cs if c in ci and valid[ci[c]]]
        if not mem: continue
        sd = sorted(S[ci[c]] for c in mem if S[ci[c]] >= 0)
        clu = max((sum(1 for x in sd if s0 <= x < s0 + CLU_D) for s0 in sd), default=0)
        recent = sum(1 for x in sd if x > tEnd - CLU_D)
        themes.append({'t': t, 'g': grp.get(t, ''), 'n': len(mem), 'b': len(sd), 'r5': recent, 'clu': clu >= CLU_N,
                       'first': dates[sd[0]] if sd else None, 'mem': mem})
    return {'date': B, 'label': a.get('label', ''), 'current': bool(a.get('current')), 'end': dates[tEnd],
            'tracked': int(tEnd - tB), 'N': int(N), 'nb': len(broke),
            'taiex': {'b': taiex.get(B), 'last': taiex.get(dates[tEnd]), 'hi': pre_hi, 'hi_d': pre_hi_d},
            'days': days, 'rows': rows, 'pend': pend, 'themes': themes}


def main():
    z = np.load(os.path.join(ROOT, 'cache', 'wh_adj.npz'))
    D, codes = [str(x) for x in z['dates']], [str(x) for x in z['codes']]
    adj, adjH, close, pct = z['adj'], z['adjH'], z['close'], z['pct']
    px = json.load(gzip.open(os.path.join(ROOT, 'cache', 'wh_px.json.gz'), 'rt', encoding='utf-8'))
    name, mkt = px['name'], px['mkt']
    w = json.load(open(os.path.join(ROOT, 'docs', 'wh.json')))
    taiex = dict(zip(w['dates'], w['taiex']))
    cfg = json.load(open(os.path.join(ROOT, 'config', 'newhigh.json'), encoding='utf-8'))
    amt = avg_amount(D, D[-1])
    out = {'asof': D[-1], 'default': cfg['default'], 'win': WIN, 'near': NEAR, 'clu': [CLU_D, CLU_N], 'anchors': []}
    for a in cfg['anchors']:
        a = dict(a, current=(a['date'] == cfg['default']))
        r = build_anchor(a, D, codes, adj, adjH, close, pct, taiex, w['dates'], name, mkt, amt)
        out['anchors'].append(r)
        print(a['date'], 'N', r['N'], '已創高', r['nb'], '追蹤', r['tracked'], '日', '接近', sum(1 for x in r['pend'] if x['vk'] is not None and x['vk'] > -NEAR))
    json.dump(out, open(os.path.join(ROOT, 'docs', 'newhigh.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print('size', os.path.getsize(os.path.join(ROOT, 'docs', 'newhigh.json')))


if __name__ == '__main__':
    main()
