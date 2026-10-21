"""市場階段（規則 MP01，Ed 2026-10-21 指示；門檻依 2020-03、2022-10、2024-08、2025-04、2026-07 五次底部整理，為初稿）。

每日數值（以延續性標籤為基礎，皆取近 5 個交易日平均以降低跳動）：
  W5 ＝「轉弱」族群數    S5 ＝「主流＋延續」族群數（站穩月線）    主流族群數＝該週主流天數 ≥3 的族群數
階段（每日依序判斷）：
  洗乾淨   W5 ≥ 55
  轉好起點 最近 40 個交易日內出現過洗乾淨，且 S5 ≥ 40、W5 ≤ 10
  確認     最近兩個完整週的主流族群數都 ≥ 10，且兩週的轉弱平均都 ≤ 3；之後維持為「延續中」
  退潮     延續中，本週（或最近完整週）主流族群數不到上一完整週的一半，且 W5 ≥ 20
  惡化     W5 ≥ 30（且不在以上階段）
  中性     其他
只供觀察，不是交易訊號。
"""
import datetime

P = dict(washed=55, turn_s=40, turn_w=10, washed_window=40, confirm_main=10, confirm_w=3, fade_w=20, worse=30)
RULE = 'MP01'
PHASE = ['中性', '惡化', '洗乾淨', '轉好起點', '延續中', '退潮', '確認']  # 6＝確認（當日首次成立），之後為 4


def compute(days):
    n = len(days)
    W = [d['L'].count('W') for d in days]
    S = [d['L'].count('M') + d['L'].count('C') for d in days]
    M = [d['L'].count('M') for d in days]
    avg5 = lambda a, k: round(sum(a[max(0, k - 4):k + 1]) / len(a[max(0, k - 4):k + 1]), 1)
    wk = [datetime.date(int(d['d'][:4]), int(d['d'][4:6]), int(d['d'][6:])).isocalendar()[:2] for d in days]
    # 每週結算：主流族群數、該週轉弱平均
    weeks = []  # [(week, main_count, w_avg, end_index)]
    for k in range(n):
        if k == n - 1 or wk[k + 1] != wk[k]:
            s = k
            while s > 0 and wk[s - 1] == wk[k]:
                s -= 1
            main = sum(1 for v in days[k]['w'].values() if v[0] >= 3)
            weeks.append((wk[k], main, sum(W[s:k + 1]) / (k - s + 1), k))
    done_before = {}  # 日 k → 已完整結算的週（不含 k 所在週）
    wi = 0
    for k in range(n):
        while wi < len(weeks) and weeks[wi][3] < k and weeks[wi][0] != wk[k]:
            wi += 1
        done_before[k] = wi  # weeks[:wi] 為 k 之前完整週
    phase, washed_at, prev = [], -10**9, 0
    for k in range(n):
        w5, s5 = avg5(W, k), avg5(S, k)
        cur_main = sum(1 for v in days[k]['w'].values() if v[0] >= 3)
        dw = weeks[:done_before[k]]
        last1 = dw[-1] if dw else None
        last2 = dw[-2:] if len(dw) >= 2 else []
        confirm = len(last2) == 2 and all(x[1] >= P['confirm_main'] and x[2] <= P['confirm_w'] for x in last2)
        if w5 >= P['washed']:
            p = 2; washed_at = k
        elif prev in (4, 6):
            ref = last1[1] if last1 else 0
            p = 5 if (ref and max(cur_main, 0) <= ref / 2 and w5 >= P['fade_w'] and wk[k] != last1[0]) else 4
            if p == 4 and not confirm and cur_main < P['confirm_main'] and last1 and last1[1] < P['confirm_main']:
                p = 5 if w5 >= P['fade_w'] else 0
        elif confirm:
            p = 6
        elif k - washed_at <= P['washed_window'] and s5 >= P['turn_s'] and w5 <= P['turn_w']:
            p = 3
        elif w5 >= P['worse']:
            p = 1
        else:
            p = 0
        days[k]['mp'] = [W[k], S[k], M[k], w5, s5, cur_main, p, last1[1] if last1 else 0, [(x[1], round(x[2], 1)) for x in last2]]
        phase.append(p); prev = p
    # 事件：階段改變
    events = []
    for k in range(1, n):
        if phase[k] != phase[k - 1]:
            events.append({'d': days[k]['d'], 'from': PHASE[phase[k - 1]], 'to': PHASE[phase[k]], 'w5': days[k]['mp'][3], 's5': days[k]['mp'][4], 'main': days[k]['mp'][7]})
    return events
