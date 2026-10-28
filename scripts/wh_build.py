"""權值與高價股觀察分頁：計算每日指標，輸出 docs/wh.json。

組別：all（上市櫃普通股）、twse（上市市值前50）、otc（上櫃市值前30）、hp（高價股前30）。
名單：每月最後交易日排名、次月使用（config/wh_lists.json）；當月尚未產生名單時沿用最近一期。
價格：還原價＝以交易所每日漲跌%（對參考價，已含除權息）連乘；無成交日沿用前值、不計入當日漲跌。
指標（每日、每組）：
  有效家數、上漲／平盤／下跌、漲停（交易所漲停價）、跌停（收盤＝依參考價與升降單位推得的跌停價）
  漲跌幅分布：≤-9%、-9～-5、-5～-3、-3～-1、-1～0、0、0～1、1～3、3～5、5～9、≥9%（含漲停）
  站上 20/60/120/240 日均線比例（還原收盤嚴格大於簡單均線；上市未滿 N 日者不計入分母）
  創 20/60/250 日新高／新低家數（還原收盤高於／低於前 N 日最高／最低收盤；歷史不足不計）
  離近 250 日最高還原收盤的距離分布：<5%、5～10、10～20、20～30、30～50、≥50%
  今年以來還原報酬中位數（去年最後交易日為基準；年內新上市者不計）
另附加權指數收盤，以及最新交易日的個股表。
"""
import gzip, json, math, os, re

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON = re.compile(r'^[1-9]\d{3}$')
BUCKETS = [-9, -5, -3, -1, 0]          # 下界由小到大；0 單列平盤
DD = [5, 10, 20, 30, 50]


def tick(p):
    return 0.01 if p < 10 else 0.05 if p < 50 else 0.1 if p < 100 else 0.5 if p < 500 else 1 if p < 1000 else 5


def limit_down(lim):
    """跌停價：參考價×(1−漲跌幅限制) 向上取至升降單位；參考價由漲跌%（兩位小數）反推，容許 0.1 個升降單位誤差"""
    t = tick(lim)
    v = math.ceil(lim / t - 0.1) * t
    if tick(v) != t:
        t = tick(v); v = math.ceil(lim / t - 0.1) * t
    return round(v, 2)


def taiex_level(ds):
    p = os.path.join(ROOT, 'archive', 'raw', 'twse', ds + '.json.gz')
    if not os.path.exists(p): return None
    for t in json.load(gzip.open(p)).get('tables') or []:
        if '價格指數' in (t.get('title') or ''):
            for r in t.get('data') or []:
                if '發行量加權股價指數' in r[0]:
                    try: return float(r[1].replace(',', ''))
                    except ValueError: return None
    return None


def main():
    d = json.load(gzip.open(os.path.join(ROOT, 'cache', 'wh_px.json.gz'), 'rt', encoding='utf-8'))
    dates, px, osh, name = d['dates'], d['px'], d['otc_sh'], d['name']
    codes = sorted(c for c in px if COMMON.match(c) and not c.startswith('91'))
    ci = {c: k for k, c in enumerate(codes)}
    T, N = len(dates), len(codes)
    pct = np.full((T, N), np.nan); lu = np.zeros((T, N), bool)
    for t, ds in enumerate(dates):
        q = json.load(open(os.path.join(ROOT, 'data', 'quotes', ds + '.json')))['q']
        for c, v in q.items():
            k = ci.get(c)
            if k is not None:
                pct[t, k] = v[0]; lu[t, k] = bool(v[2]) if len(v) > 2 else False
    close = np.array([[px[c][t] if px[c][t] else np.nan for c in codes] for t in range(T)])
    traded = ~np.isnan(close) & ~np.isnan(pct)
    ld = np.zeros((T, N), bool)
    for t, ds in enumerate(dates):
        lim_pct = 0.93 if ds < '20150601' else 0.90
        for k in np.where(traded[t] & (pct[t] <= -6.5))[0]:
            c = close[t, k]; ref = c / (1 + pct[t, k] / 100)
            ld[t, k] = abs(c - limit_down(ref * lim_pct)) < 1e-6  # 收盤低於跌停價者（首五日無漲跌幅等）不算
    # 還原價：首日以收盤為起點，之後以漲跌% 連乘；無成交沿用
    adj = np.full((T, N), np.nan)
    last = np.full(N, np.nan)
    for t in range(T):
        new = np.isnan(last) & ~np.isnan(close[t])
        last = np.where(new, close[t], last)
        upd = traded[t] & ~new
        last = np.where(upd, last * (1 + pct[t] / 100), last)
        adj[t] = last
    age = np.cumsum(~np.isnan(adj), axis=0)  # 已上市交易日數

    def rolling(fn, n):
        out = np.full((T, N), np.nan)
        for t in range(n, T):
            out[t] = fn(adj[t - n:t], axis=0)  # 前 n 日（不含當日）
        return out
    ma = {}
    for n in (20, 60, 120, 240):
        cs = np.nancumsum(np.nan_to_num(adj), axis=0)
        s = np.full((T, N), np.nan)
        s[n - 1:] = cs[n - 1:] - np.vstack([np.zeros((1, N)), cs[:-n]])
        ma[n] = s / n
    hi = {n: rolling(np.nanmax, n) for n in (20, 60, 250)}
    lo = {n: rolling(np.nanmin, n) for n in (20, 60, 250)}
    hi250in = np.full((T, N), np.nan)
    for t in range(T):
        hi250in[t] = np.nanmax(adj[max(0, t - 249):t + 1], axis=0)
    # 年初基準
    ybase = {}
    for t, ds in enumerate(dates):
        ybase[ds[:4]] = t  # 每年最後一日索引（之後用前一年）

    lists = json.load(open(os.path.join(ROOT, 'config', 'wh_lists.json')))
    yms = sorted(lists)

    def members(ds, g):
        prev = [ym for ym in yms if ym < ds[:6]]
        if not prev: return None
        return [c for c, _ in lists[prev[-1]][g]]

    is_otc = {c: (c in osh) for c in codes}
    G = ['all', 'twse', 'otc', 'hp']
    out = {g: {k: [] for k in ['n', 'up', 'flat', 'down', 'lu', 'ld', 'dist', 'ma', 'mad', 'hi', 'lo', 'hld', 'dd', 'ytd']} for g in G}
    taiex = []
    for t, ds in enumerate(dates):
        taiex.append(taiex_level(ds))
        yb = ybase.get(str(int(ds[:4]) - 1))
        for g in G:
            if g == 'all':
                idx = np.where(traded[t])[0]
            else:
                m = members(ds, g)
                idx = np.array([ci[c] for c in (m or []) if c in ci and traded[t, ci[c]]], int)
            o = out[g]
            if len(idx) == 0:
                for k in o: o[k].append(None)
                continue
            p = pct[t, idx]
            o['n'].append(int(len(idx))); o['up'].append(int((p > 0).sum())); o['flat'].append(int((p == 0).sum()))
            o['down'].append(int((p < 0).sum())); o['lu'].append(int(lu[t, idx].sum())); o['ld'].append(int(ld[t, idx].sum()))
            dist = [int((p <= -9).sum()), int(((p > -9) & (p <= -5)).sum()), int(((p > -5) & (p <= -3)).sum()),
                    int(((p > -3) & (p <= -1)).sum()), int(((p > -1) & (p < 0)).sum()), int((p == 0).sum()),
                    int(((p > 0) & (p < 1)).sum()), int(((p >= 1) & (p < 3)).sum()), int(((p >= 3) & (p < 5)).sum()),
                    int(((p >= 5) & (p < 9)).sum()), int((p >= 9).sum())]
            o['dist'].append(dist)
            a = adj[t, idx]
            mav, mad = [], []
            for n in (20, 60, 120, 240):
                ok = age[t, idx] >= n
                mad.append(int(ok.sum())); mav.append(int((a[ok] > ma[n][t, idx][ok]).sum()))
            o['ma'].append(mav); o['mad'].append(mad)
            h, l, hd = [], [], []
            for n in (20, 60, 250):
                ok = (age[t, idx] > n)
                hd.append(int(ok.sum()))
                h.append(int((a[ok] > hi[n][t, idx][ok]).sum())); l.append(int((a[ok] < lo[n][t, idx][ok]).sum()))
            o['hi'].append(h); o['lo'].append(l); o['hld'].append(hd)
            dd = (1 - a / hi250in[t, idx]) * 100
            o['dd'].append([int((dd < 5).sum())] + [int(((dd >= DD[i]) & (dd < DD[i + 1])).sum()) for i in range(4)] + [int((dd >= 50).sum())])
            if yb is not None:
                base = adj[yb, idx]; ok = ~np.isnan(base) & (age[yb, idx] > 0)
                o['ytd'].append(round(float(np.median(a[ok] / base[ok] - 1) * 100), 2) if ok.any() else None)
            else:
                o['ytd'].append(None)

    # 最新交易日個股表（四組成員聯集）
    t = T - 1; ds = dates[t]; yb = ybase.get(str(int(ds[:4]) - 1))
    mem = {g: (members(ds, g) or []) for g in ['twse', 'otc', 'hp']}
    rows = []
    for c in sorted(set(sum(mem.values(), []))):
        k = ci.get(c)
        if k is None: continue
        a = adj[t, k]
        def r(n):
            return round(float(a / adj[t - n, k] - 1) * 100, 2) if t >= n and not np.isnan(adj[t - n, k]) and not np.isnan(a) else None
        rows.append({
            'c': c, 'n': name.get(c, ''), 'g': [g for g in mem if c in mem[g]],
            'px': None if np.isnan(close[t, k]) else close[t, k], 'pct': None if np.isnan(pct[t, k]) else round(float(pct[t, k]), 2),
            'ytd': round(float(a / adj[yb, k] - 1) * 100, 2) if yb is not None and not np.isnan(adj[yb, k]) else None,
            'r20': r(20), 'dd': None if np.isnan(a) else round(float((1 - a / hi250in[t, k]) * 100), 1),
            'ma': [None if age[t, k] < n else bool(a > ma[n][t, k]) for n in (20, 60, 120, 240)],
            'hi': [bool(age[t, k] > n and a > hi[n][t, k]) for n in (20, 60, 250)],
            'lo': [bool(age[t, k] > n and a < lo[n][t, k]) for n in (20, 60, 250)],
        })
    lists_out = {ym: {g: [c for c, _ in lists[ym][g]] for g in ['twse', 'otc', 'hp']} | {'asof': lists[ym]['asof']} for ym in yms}
    res = {'dates': dates, 'taiex': taiex, 'groups': out, 'stocks': rows, 'stock_date': ds, 'lists': lists_out, 'names': {c: name.get(c, '') for c in set(c for v in lists_out.values() for g in ('twse', 'otc', 'hp') for c in v[g])}}
    json.dump(res, open(os.path.join(ROOT, 'docs', 'wh.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print('days', T, 'codes', N, 'stocks', len(rows), 'size', os.path.getsize(os.path.join(ROOT, 'docs', 'wh.json')))


if __name__ == '__main__':
    main()
