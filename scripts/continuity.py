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
規則 C02（Ed 2026-10-23 確認，依審查意見修正）：
  1. 每週最後一個交易日收盤即結算該週（原為下週一才結算）。最新一日是否為該週最後交易日：
     該週其餘平日都已過去（當日無資料）或列於證交所休市日期表，即視為該週結束。
  2. 交易日少於 3 天的週（春節、連假等短週）不計入：既不算達標，也不算中斷。
"""
import datetime


def week_end_flags(days):
    """每日是否為該 ISO 週最後一個交易日（C02）。歷史日看下一筆資料是否換週；
    最新一日看該週剩餘平日是否都已過去或為公告休市日（查不到休市表時視為未結束）。"""
    n = len(days)
    dt = [datetime.date(int(d['d'][:4]), int(d['d'][4:6]), int(d['d'][6:])) for d in days]
    wk = [x.isocalendar()[:2] for x in dt]
    flags = [k < n - 1 and wk[k + 1] != wk[k] for k in range(n)]
    if n:
        last = dt[-1]
        today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date()
        rest = [last + datetime.timedelta(days=i) for i in range(1, 5 - last.weekday())]  # 同週其餘週一～週五
        import os
        cf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'closed.txt')
        extra = set(open(cf).read().split()) if os.path.exists(cf) else set()

        def closed(x):
            if x.strftime('%Y%m%d') in extra:
                return True  # 臨時停止交易（颱風等），記於 data/closed.txt
            if x < today:
                return True  # 已過去且沒有資料（休市、颱風停止交易）
            try:
                import quotes
                return quotes.is_holiday(x)
            except Exception:
                return False
        flags[-1] = all(closed(x) for x in rest)
    return flags, wk

C = dict(ma=20, hi=60, near=0.97, cons_main=0.70, cons_cont=0.50, cons_weak=0.40, hits_main=8, week_min=3)
MIN_MEMBERS = 3
MIN_MEMBERS_EXCEPT = {'航空': 2}  # Ed 2026-10-21：航空放寬為 2 檔
RULE = 'C02'
SHORT_WEEK = 3  # 交易日少於此數的週不計入（C02）


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
    # 週欄位（C02：每週最後交易日收盤即結算；交易日 <3 的短週不計入）
    wend, wk = week_end_flags(days)
    st = [{'m': [0, 0], 'c': [0, 0]} for _ in names]  # [連續週數, 連續未達週數]（已結算週）
    cur = [[0, 0] for _ in names]  # 本週 [主流天數, 主流或延續天數]
    ndays = 0  # 本週已過交易日數
    for k, d in enumerate(days):
        if k and wk[k] != wk[k - 1]:
            cur = [[0, 0] for _ in names]
            ndays = 0
        ndays += 1
        for ti in range(len(names)):
            lab = labels[k][ti]
            cur[ti][0] += lab == 'M'
            cur[ti][1] += lab in ('M', 'C')
        if wend[k] and ndays >= SHORT_WEEK:  # 本週結束：結算（短週不結算）
            for ti in range(len(names)):
                for key, cnt in (('m', cur[ti][0]), ('c', cur[ti][1])):
                    s = st[ti][key]
                    if cnt >= C['week_min']:
                        s[0] += 1; s[1] = 0
                    else:
                        s[1] += 1
                        if s[1] >= 2:
                            s[0] = 0
        out = {}
        for ti in range(len(names)):
            if wend[k]:  # 已結算（或短週不計）：直接顯示結算後週數
                ms, cs = st[ti]['m'][0], st[ti]['c'][0]
            else:
                ms = st[ti]['m'][0] + (1 if cur[ti][0] >= C['week_min'] else 0)
                cs = st[ti]['c'][0] + (1 if cur[ti][1] >= C['week_min'] else 0)
            if cur[ti][0] or cur[ti][1] or ms or cs:
                out[ti] = [cur[ti][0], cur[ti][1], ms, cs]
        d['L'] = ''.join(l or '-' for l in labels[k])
        d['w'] = out
        d['we'] = 1 if wend[k] else 0  # 該週已結束（供市場階段判斷完整週；輸出前移除）
