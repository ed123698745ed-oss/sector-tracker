"""市場非常態（瘋狂）判定：下跌瘋狂、上漲瘋狂、資金集中炒作。Ed 2026-10-29 指定非常態約占 10～15% 交易日。

每日指標（全市場上市櫃普通股）在「2005/01/01 起至當日」的歷史百分位（只用當日以前資料，無前視）：
  下跌分數＝平均（5日跌幅、20日跌幅、5日跌停家數占比、20日報酬波動度、離250日高點≥20%占比）
  上漲分數＝平均（20日漲幅、加權指數對60日均線乖離、20日均成交值÷250日均成交值、5日漲停家數占比）
  資金集中＝前5大成交值個股（排除台積電）占普通股成交值比重的5日平均之百分位
狀態（進入／退出門檻，遲滯避免一天亮一天暗）：
  下跌瘋狂 0.85／0.72；上漲瘋狂 0.87／0.80；資金集中 0.985／0.96；同時符合時下跌優先、其次上漲。
只供觀察，不是交易訊號。
"""
import bisect, math

START = '20050101'
MINHIST = 250   # 至少累積 250 個交易日歷史才計算百分位（約 2006 年起有判定）
TH = {'down': (0.85, 0.72), 'up': (0.87, 0.80), 'conc': (0.985, 0.96)}


def _roll(x, k, fn):
    out = [None] * len(x)
    for i in range(k - 1, len(x)):
        w = [v for v in x[i - k + 1:i + 1] if v is not None]
        out[i] = fn(w) if len(w) == k else None
    return out


def _mean(w): return sum(w) / len(w)


def _std(w):
    m = _mean(w); return math.sqrt(sum((v - m) ** 2 for v in w) / len(w))


def _expanding_pr(x, dates):
    """當日值在 2005 起至當日（含）歷史中的百分位"""
    hist, out = [], [None] * len(x)
    for i, v in enumerate(x):
        if v is None or dates[i] < START: continue
        bisect.insort(hist, v)
        if len(hist) >= MINHIST: out[i] = bisect.bisect_right(hist, v) / len(hist)
    return out


def compute(dates, taiex, allg, turnover, conc):
    T = len(dates)
    tx = []
    for v in taiex:
        tx.append(v if v else (tx[-1] if tx else None))
    lag = lambda x, k: [None] * k + x[:-k]
    def ratio(a, b): return [a[i] / b[i] - 1 if a[i] and b[i] else None for i in range(T)]
    ret = [None] + [tx[i] / tx[i - 1] - 1 if tx[i] and tx[i - 1] else None for i in range(1, T)]
    r5, r20 = ratio(tx, lag(tx, 5)), ratio(tx, lag(tx, 20))
    vol20 = _roll(ret, 20, _std)
    ma60 = _roll(tx, 60, _mean); bias = ratio(tx, ma60)
    t20, t250 = _roll(turnover, 20, _mean), _roll(turnover, 250, _mean)
    turnr = [t20[i] / t250[i] if t20[i] and t250[i] else None for i in range(T)]
    n = allg['n']
    ldr = [allg['ld'][i] / n[i] if n[i] else None for i in range(T)]
    lur = [allg['lu'][i] / n[i] if n[i] else None for i in range(T)]
    ld5, lu5 = _roll(ldr, 5, sum), _roll(lur, 5, sum)
    dd = [(v[3] + v[4] + v[5]) / sum(v) if v and sum(v) else None for v in allg['dd']]
    conc5 = _roll(conc, 5, _mean)
    neg = lambda x: [-v if v is not None else None for v in x]
    P = {k: _expanding_pr(v, dates) for k, v in dict(nr5=neg(r5), nr20=neg(r20), ld5=ld5, vol=vol20, dd=dd,
                                                    r20=r20, bias=bias, turn=turnr, lu5=lu5, conc=conc5).items()}
    def avg(keys, i):
        vs = [P[k][i] for k in keys if P[k][i] is not None]
        return sum(vs) / len(vs) if len(vs) == len(keys) else None
    down = [avg(['nr5', 'nr20', 'ld5', 'vol', 'dd'], i) for i in range(T)]
    up = [avg(['r20', 'bias', 'turn', 'lu5'], i) for i in range(T)]
    cc = P['conc']
    state, s = [0] * T, 0
    for i in range(T):
        dv, uv, cv = down[i], up[i], cc[i]
        if s == -1 and dv is not None and dv >= TH['down'][1]: state[i] = -1; continue
        if s == 1 and uv is not None and uv >= TH['up'][1]: state[i] = 1; continue
        if s == 2 and cv is not None and cv >= TH['conc'][1]: state[i] = 2; continue
        s = 0
        if dv is not None and dv >= TH['down'][0]: s = -1
        elif uv is not None and uv >= TH['up'][0]: s = 1
        elif cv is not None and cv >= TH['conc'][0]: s = 2
        state[i] = s
    r = lambda x: [round(v, 3) if v is not None else None for v in x]
    return {'state': state, 'down': r(down), 'up': r(up), 'conc': r(cc), 'th': TH}
