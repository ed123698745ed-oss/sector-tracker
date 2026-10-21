"""族群延續性指標（Elon 交接 2026-10-21，Ed 確認；延續性規則 C01）。

每日標籤（依序判斷，符合即停）：
  主流 M：族群指數站上 20 日均線、一致性 ≥70%，且（族群指數 ≥ 60 日最高 × 0.97，或近 20 日上榜 ≥8 天）
  延續 C：站月線、一致性 ≥50%
  分化 D：站月線、一致性 <50%
  轉弱 W：未站月線、一致性 <40%
  盤整 S：其他
  不給標籤：族群指數資料不足 60 個交易日、有效期間外、符合條件成分股少於 3 檔（航空放寬為 2 檔）。

族群指數＝每日有成交成分股漲跌% 平均，逐日連乘（等權、每日再平衡）。
一致性＝符合條件成分股中，價格站上自身 20 日均線的比例；個股價格由每日漲跌% 連乘，
只計入最近 20 個交易日都有價格（上市滿 20 日、且最近 5 日內有成交）的成分股。

週欄位（ISO 週）：本週主流天數、本週主流或延續天數；主流週／延續週＝一週 ≥3 天。
連續週數容許中斷 1 週（中斷那週不計入），連續 2 週未達才歸零；本週未達 3 天時沿用上週為止的連續數。
"""
import datetime

C = dict(ma=20, hi=60, near=0.97, cons_main=0.70, cons_cont=0.50, cons_weak=0.40, hits_main=8, week_min=3)
MIN_MEMBERS = 3
MIN_MEMBERS_EXCEPT = {'航空': 2}  # Ed 2026-10-21：航空放寬為 2 檔
RULE = 'C01'


def compute(days, qs, th, names):
    """days：build 產生的每日資料（含 t 列）；qs：每日 {代號: 漲跌%}（已排除新上市前五日）。
    直接在每個 day 加上 L（標籤字串，每題材一字元，'-'＝無標籤）與 w（{題材序: [本週主流天數, 本週主流或延續天數, 連續主流週, 連續延續週]}）。"""
    n = len(days)
    codes = sorted({c for t in names for c, _ in th[t]})
    # 個股價格（連乘，未出現前為 None，之後無成交沿用前值）
    price = {c: [None] * n for c in codes}
    first, last = {}, {}
    for k, q in enumerate(qs):
        for c in codes:
            prev = price[c][k - 1] if k else None
            if c in q:
                price[c][k] = (prev if prev is not None else 100.0) * (1 + q[c] / 100)
                first.setdefault(c, k); last[c] = k
            else:
                price[c][k] = prev
    labels = [[''] * len(names) for _ in range(n)]
    for ti, t in enumerate(names):
        idx, start = [None] * n, None
        for k, d in enumerate(days):
            r = d['t'][ti]
            if not r:  # 有效期間外：指數中斷
                start = None
                continue
            if start is None:
                start, base = k, 100.0
            else:
                base = idx[k - 1]
            idx[k] = base * (1 + (r[1] or 0) / 100)
            if k - start + 1 < C['hi']:
                continue
            win = idx[k - C['ma'] + 1:k + 1]
            above = idx[k] >= sum(win) / len(win)
            near = idx[k] >= max(idx[k - C['hi'] + 1:k + 1]) * C['near']
            hits20 = sum(1 for j in range(k - C['ma'] + 1, k + 1) if days[j]['t'][ti] and days[j]['t'][ti][0])
            elig = up = 0
            for c, _ in th[t]:
                if c not in first or first[c] > k - C['ma'] + 1:  # 上市未滿 20 日
                    continue
                if not any(c in qs[j] for j in range(max(0, k - 4), k + 1)):  # 最近 5 日無成交（停牌、下市）
                    continue
                pw = price[c][k - C['ma'] + 1:k + 1]
                elig += 1
                up += pw[-1] >= sum(pw) / len(pw)
            if elig < MIN_MEMBERS_EXCEPT.get(t, MIN_MEMBERS):
                continue
            cons = up / elig
            if above and cons >= C['cons_main'] - 1e-9 and (near or hits20 >= C['hits_main']):
                lab = 'M'
            elif above and cons >= C['cons_cont'] - 1e-9:
                lab = 'C'
            elif above:
                lab = 'D'
            elif cons < C['cons_weak'] - 1e-9:
                lab = 'W'
            else:
                lab = 'S'
            labels[k][ti] = lab
    # 週欄位
    wk = [datetime.date(int(d['d'][:4]), int(d['d'][4:6]), int(d['d'][6:])).isocalendar()[:2] for d in days]
    st = [{'m': [0, 0], 'c': [0, 0]} for _ in names]  # [連續週數, 連續未達週數]
    cur = [[0, 0] for _ in names]  # 本週 [主流天數, 主流或延續天數]
    for k, d in enumerate(days):
        if k and wk[k] != wk[k - 1]:  # 上週結束：結算
            for ti in range(len(names)):
                for key, cnt in (('m', cur[ti][0]), ('c', cur[ti][1])):
                    s = st[ti][key]
                    if cnt >= C['week_min']:
                        s[0] += 1; s[1] = 0
                    else:
                        s[1] += 1
                        if s[1] >= 2:
                            s[0] = 0
                cur[ti] = [0, 0]
        out = {}
        for ti in range(len(names)):
            lab = labels[k][ti]
            cur[ti][0] += lab == 'M'
            cur[ti][1] += lab in ('M', 'C')
            ms = st[ti]['m'][0] + (1 if cur[ti][0] >= C['week_min'] else 0)
            cs = st[ti]['c'][0] + (1 if cur[ti][1] >= C['week_min'] else 0)
            if cur[ti][0] or cur[ti][1] or ms or cs:
                out[ti] = [cur[ti][0], cur[ti][1], ms, cs]
        d['L'] = ''.join(l or '-' for l in labels[k])
        d['w'] = out
