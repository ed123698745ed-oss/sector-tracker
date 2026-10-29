"""權值與高價股觀察分頁：計算每日指標，輸出 docs/wh.json。

組別：all（上市櫃普通股）、twse（上市市值前50）、otc（上櫃市值前30）、hp（高價股前30）。
名單：每月最後交易日排名、次月使用（config/wh_lists.json）；當月尚未產生名單時沿用最近一期。
價格：還原價＝以交易所每日漲跌%（對參考價，已含除權息）連乘；無成交日沿用前值、不計入當日漲跌。
指標（每日、每組）：
  有效家數、上漲／平盤／下跌、漲停（交易所漲停價）、跌停（收盤＝依參考價與升降單位推得的跌停價）
  漲跌幅分布：≤-9%、-9～-5、-5～-3、-3～-1、-1～0、0、0～1、1～3、3～5、5～9、≥9%（含漲停）
  站上 20/60/120/240 日均線比例（還原收盤嚴格大於簡單均線；上市未滿 N 日者不計入分母）
  創 20/60/250 日新高／新低家數（當日最高價高於前 N 日最高價／當日最低價低於前 N 日最低價，皆為還原值；歷史不足不計）
  收盤離近 250 日最高價（含當日、還原值）的距離分布：<5%、5～10、10～20、20～30、30～50、≥50%
  今年以來還原報酬中位數（去年最後交易日為基準；年內新上市者不計）
另附加權指數收盤，以及最新交易日的個股表。
"""
import gzip, json, math, os, re

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON = re.compile(r'^[1-9]\d{3}$')
BUCKETS = [-9, -5, -3, -1, 0]          # 下界由小到大；0 單列平盤
DD = [5, 10, 20, 30, 50]


_FM = {}


def taiex_fmtqik(ds):
    """2009 年以前 MI_INDEX 無指數表：改用大盤日成交資訊 FMTQIK 的加權指數收盤"""
    ym = ds[:6]
    if ym not in _FM:
        p = os.path.join(ROOT, 'archive', 'raw', 'twse_fmtqik', ym + '.json')
        _FM[ym] = {}
        if os.path.exists(p):
            for r in json.load(open(p)).get('data') or []:
                a, b, c = r[0].strip().split('/')
                _FM[ym]['%d%s%s' % (int(a) + 1911, b, c)] = float(r[4].replace(',', ''))
    return _FM[ym].get(ds)


def taiex_level(ds):
    p = os.path.join(ROOT, 'archive', 'raw', 'twse', ds + '.json.gz')
    if not os.path.exists(p) or ds < '20090101': return taiex_fmtqik(ds)
    for t in json.load(gzip.open(p)).get('tables') or []:
        if '價格指數' in (t.get('title') or ''):
            for r in t.get('data') or []:
                if '發行量加權股價指數' in r[0]:
                    try: return float(r[1].replace(',', ''))
                    except ValueError: return None
    return taiex_fmtqik(ds)


def main():
    d = json.load(gzip.open(os.path.join(ROOT, 'cache', 'wh_px.json.gz'), 'rt', encoding='utf-8'))
    dates, px, osh, name = d['dates'], d['px'], d['otc_sh'], d['name']
    codes = sorted(c for c in px if COMMON.match(c) and not c.startswith('91'))
    ci = {c: k for k, c in enumerate(codes)}
    T, N = len(dates), len(codes)
    pct = np.full((T, N), np.nan)
    for t, ds in enumerate(dates):
        q = json.load(open(os.path.join(ROOT, 'data', 'quotes', ds + '.json')))['q']
        for c, v in q.items():
            k = ci.get(c)
            if k is not None:
                pct[t, k] = v[0]
    close = np.array([[px[c][t] if px[c][t] else np.nan for c in codes] for t in range(T)])
    # 上市減資、變更面額（分割）恢復買賣首日：每日行情檔無漲跌%（不比價），改以證交所公告的恢復買賣參考價計算，
    # 否則還原價會漏掉當日漲跌（例：國巨 2025/8/25 面額分割恢復買賣）
    ev = {}
    edir = os.path.join(ROOT, 'archive', 'raw', 'twse_events')
    for fn in os.listdir(edir):
        if not fn.startswith(('TWTAUU', 'TWTB8U')): continue
        for r in json.load(open(os.path.join(edir, fn))).get('data') or []:
            y, m, dd = r[0].split('/')
            try: ev[('%d%s%s' % (int(y) + 1911, m, dd), r[1].strip())] = float(r[4].replace(',', ''))
            except ValueError: pass
    import bisect
    fixed = 0
    for (ds, c), ref in ev.items():
        k = ci.get(c); t0 = bisect.bisect_left(dates, ds)
        if k is None or ref <= 0: continue
        for t in range(t0, min(t0 + 3, T)):  # 公告日期偶有早於實際恢復買賣日一天
            if not np.isnan(close[t, k]):
                if np.isnan(pct[t, k]): pct[t, k] = (close[t, k] / ref - 1) * 100; fixed += 1
                break
    # 上櫃轉上市首日：上市行情檔無漲跌%，以前一交易日上櫃收盤計算（前一日有上櫃發行股數、當日沒有＝已轉市）。
    # 其他無漲跌%的日子（例：2007 年上櫃除權息日查無參考價）不補，避免把除權息缺口算成漲跌
    for k, c in enumerate(codes):
        if c not in osh: continue
        for t in np.where(np.isnan(pct[:, k]) & ~np.isnan(close[:, k]))[0]:
            if t > 0 and not np.isnan(close[t - 1, k]) and osh[c][t - 1] and not osh[c][t]:
                pct[t, k] = (close[t, k] / close[t - 1, k] - 1) * 100; fixed += 1
    print('無漲跌%的交易日補算：', fixed)
    traded = ~np.isnan(close) & ~np.isnan(pct)
    # 漲跌停：wh_prices.py 依當時制度由原始行情判定（上市：參考價＋升降單位新舊制、7%／10%、2008/10 跌幅 3.5%，
    # 除權息與恢復買賣日用證交所公告漲跌停價；上櫃：前一交易日公布之次日漲跌停價）。收盤＝漲（跌）停價才算
    limarr = np.array([[(d['lim'][c][t] if d['lim'][c][t] is not None else 0) for c in codes] for t in range(T)])
    lu = (limarr == 1) & traded; ld = (limarr == -1) & traded
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

    # 盤中最高／最低的還原值＝還原收盤 × 當日最高（最低）÷ 收盤；無成交日不計
    hraw = np.array([[d['hi'][c][t] or np.nan for c in codes] for t in range(T)])
    lraw = np.array([[d['lo'][c][t] or np.nan for c in codes] for t in range(T)])
    adjH = np.where(traded, adj * hraw / close, np.nan)
    adjL = np.where(traded, adj * lraw / close, np.nan)

    def rolling(fn, n, src):
        out = np.full((T, N), np.nan)
        for t in range(n, T):
            out[t] = fn(src[t - n:t], axis=0)  # 前 n 日（不含當日）
        return out
    ma = {}
    for n in (20, 60, 120, 240):
        cs = np.nancumsum(np.nan_to_num(adj), axis=0)
        s = np.full((T, N), np.nan)
        s[n - 1:] = cs[n - 1:] - np.vstack([np.zeros((1, N)), cs[:-n]])
        ma[n] = s / n
    hi = {n: rolling(np.nanmax, n, adjH) for n in (20, 60, 250)}  # 前 n 日最高價
    lo = {n: rolling(np.nanmin, n, adjL) for n in (20, 60, 250)}  # 前 n 日最低價
    hi250in = np.full((T, N), np.nan)
    for t in range(T):
        hi250in[t] = np.nanmax(adjH[max(0, t - 249):t + 1], axis=0)  # 近 250 日（含當日）最高價
    # 年初基準
    ybase = {}
    for t, ds in enumerate(dates):
        ybase[ds[:4]] = t  # 每年最後一日索引（之後用前一年）

    lists = json.load(open(os.path.join(ROOT, 'config', 'wh_lists.json')))
    yms = sorted(lists)

    def members(ds, g):
        prev = [ym for ym in yms if ym < ds[:6]]
        if not prev: return None
        return [c for c, _ in lists[prev[-1]].get(g, [])]

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
                h.append(int((adjH[t, idx][ok] > hi[n][t, idx][ok]).sum())); l.append(int((adjL[t, idx][ok] < lo[n][t, idx][ok]).sum()))
            o['hi'].append(h); o['lo'].append(l); o['hld'].append(hd)
            okd = age[t, idx] >= 250   # 離 250 日高點：需有 250 個交易日歷史，不足者不列入（2005/02 前全部暖機中）
            dd = (1 - a[okd] / hi250in[t, idx][okd]) * 100
            o['dd'].append([int((dd < 5).sum())] + [int(((dd >= DD[i]) & (dd < DD[i + 1])).sum()) for i in range(4)] + [int((dd >= 50).sum())] if okd.any() else None)
            if yb is not None:
                base = adj[yb, idx]; ok = ~np.isnan(base) & (age[yb, idx] > 0)
                o['ytd'].append(round(float(np.median(a[ok] / base[ok] - 1) * 100), 2) if ok.any() else None)
            else:
                o['ytd'].append(None)

    # 最新交易日個股表（四組成員聯集）
    t = T - 1; ds = dates[t]; yb = ybase.get(str(int(ds[:4]) - 1))
    mem = {g: (members(ds, g) or []) for g in ['twse', 'otc', 'hp']}
    # 市值（億）＝最新收盤 × 發行股數（上市：最近一份證交所 MI_QFIIS；上櫃：櫃買當日發行股數）
    qdir = os.path.join(ROOT, 'archive', 'raw', 'twse_qfiis')
    qlast = max((f for f in os.listdir(qdir) if f[:8] <= ds), default=None)
    qsh = {r[0].strip(): int(r[3].replace(',', '')) for r in json.load(gzip.open(os.path.join(qdir, qlast)))['data']} if qlast else {}
    rows = []
    for c in sorted(set(sum(mem.values(), []))):
        k = ci.get(c)
        if k is None: continue
        a = adj[t, k]
        def r(n):
            return round(float(a / adj[t - n, k] - 1) * 100, 2) if t >= n and not np.isnan(adj[t - n, k]) and not np.isnan(a) else None
        rows.append({
            'c': c, 'n': name.get(c, ''), 'g': [g for g in mem if c in mem[g]],
            'px': None if np.isnan(close[t, k]) else close[t, k],
            'cap': (lambda sh: round(close[t, k] * sh / 1e8) if sh and not np.isnan(close[t, k]) else None)(
                (osh[c][t] if c in osh else None) or qsh.get(c)),  # 上櫃轉上市者上櫃股數停在轉市前，改取上市
            'pct': None if np.isnan(pct[t, k]) else round(float(pct[t, k]), 2),
            'ytd': round(float(a / adj[yb, k] - 1) * 100, 2) if yb is not None and not np.isnan(adj[yb, k]) else None,
            'r20': r(20), 'dd': None if np.isnan(a) or age[t, k] < 250 else round(float((1 - a / hi250in[t, k]) * 100), 1),
            'ma': [None if age[t, k] < n else bool(a > ma[n][t, k]) for n in (20, 60, 120, 240)],
            'hi': [bool(age[t, k] > n and adjH[t, k] > hi[n][t, k]) for n in (20, 60, 250)],
            'lo': [bool(age[t, k] > n and adjL[t, k] < lo[n][t, k]) for n in (20, 60, 250)],
        })
    lists_out = {ym: {g: [c for c, _ in lists[ym][g]] for g in ['twse', 'otc', 'hp']} | {'asof': lists[ym]['asof']} for ym in yms}
    res = {'dates': dates, 'taiex': taiex, 'groups': out, 'stocks': rows, 'stock_date': ds, 'lists': lists_out, 'names': {c: name.get(c, '') for c in set(c for v in lists_out.values() for g in ('twse', 'otc', 'hp') for c in v[g])}}
    json.dump(res, open(os.path.join(ROOT, 'docs', 'wh.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print('days', T, 'codes', N, 'stocks', len(rows), 'size', os.path.getsize(os.path.join(ROOT, 'docs', 'wh.json')))


if __name__ == '__main__':
    main()
