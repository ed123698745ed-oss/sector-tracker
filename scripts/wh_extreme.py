"""市場非常態（瘋狂）判定：下跌瘋狂、上漲瘋狂、資金集中炒作。

每日指標（全市場上市櫃普通股）在「2005/01/01 起至當日（含當日）」的 expanding 歷史百分位。
滾動窗與百分位都只讀到該日為止，不用該日之後的輸入。

  下跌分數＝平均（5日跌幅、20日跌幅、5日跌停家數占比、20日報酬波動度、離250日高點≥20%占比）的百分位
  上漲分數＝平均（20日漲幅、加權指數對60日均線乖離、20日均成交值÷250日均成交值、5日漲停家數占比）的百分位
  資金集中＝前5大成交值個股（排除台積電）占其餘普通股成交值比重的5日平均之百分位

狀態機（進入／退出皆為 >=；既有非常態優先維持，退出後才依下跌、上漲、集中的順序進入）：
  下跌瘋狂 0.85／0.72；上漲瘋狂 0.87／0.80；資金集中 0.985／0.96。
判定用未四捨五入的分數；寫出的分數以 Python round(., 3)（銀行家捨入）到小數三位。
只供觀察，不是交易訊號。

門檻變更：在 TH_VERSIONS 追加一列，不要改舊列。compute() 使用最後一列。
"""
import bisect
import math

START = '20050101'
MINHIST = 250   # 至少累積 250 個「2005-01-01 起、非缺值」觀察才計算百分位

# 門檻版本史。調整時只追加，不修改已生效列。統計與推播須標 rule id。
TH_VERSIONS = [
    {
        'id': '2026-10-29',
        'effective': '2026-10-29',
        'introduced_commit': '2def1cf129c1e44a777d117d04e8c4f21fc876f8',
        'note': '試行版初版。Ed 2026-10-29 指定非常態約占 10～15% 交易日。此列上線後未再改門檻。',
        'th': {'down': (0.85, 0.72), 'up': (0.87, 0.80), 'conc': (0.985, 0.96)},
        'start': START,
        'minhist': MINHIST,
        'priority': ['down', 'up', 'conc'],
    },
]
TH = TH_VERSIONS[-1]['th']
RULE_ID = TH_VERSIONS[-1]['id']
STATE_NAME = {-1: '下跌瘋狂', 1: '上漲瘋狂', 2: '資金集中炒作', 0: '常態'}


def _roll(x, k, fn):
    out = [None] * len(x)
    for i in range(k - 1, len(x)):
        w = [v for v in x[i - k + 1:i + 1] if v is not None]
        out[i] = fn(w) if len(w) == k else None
    return out


def _mean(w):
    return sum(w) / len(w)


def _std(w):
    m = _mean(w)
    return math.sqrt(sum((v - m) ** 2 for v in w) / len(w))


def _expanding_pr(x, dates, start=START, minh=MINHIST):
    """當日值在 start 起至當日（含）已納入歷史中的百分位。

    百分位 = count(歷史值 <= 當日值) / 歷史筆數（bisect_right）。
    start 之前的值不納入、不產生分數。缺值不納入。歷史筆數未滿 minh 則為 None。
    只會讀到 enumerate 當下的 x[i]，不會讀 x[i] 之後。
    """
    hist, out = [], [None] * len(x)
    for i, v in enumerate(x):
        if v is None or dates[i] < start:
            continue
        bisect.insort(hist, v)
        if len(hist) >= minh:
            out[i] = bisect.bisect_right(hist, v) / len(hist)
    return out


def transition(prev, dv, uv, cv, th=None):
    """由前一狀態與當日三個分數得到當日狀態。分數 None 視為未達該側門檻。

    順序：
      1. 若前態為非常態，且該狀態自己的分數仍 >= 退出門檻，維持前態（不看其他分數）。
      2. 否則先回到常態，再依下跌、上漲、集中檢查進入門檻（>=）。先符合者勝出。
    因此：遲滯優先於「同時達標」的優先序；退出與改入另一狀態可以發生在同一天。
    """
    th = TH if th is None else th
    if prev == -1 and dv is not None and dv >= th['down'][1]:
        return -1
    if prev == 1 and uv is not None and uv >= th['up'][1]:
        return 1
    if prev == 2 and cv is not None and cv >= th['conc'][1]:
        return 2
    if dv is not None and dv >= th['down'][0]:
        return -1
    if uv is not None and uv >= th['up'][0]:
        return 1
    if cv is not None and cv >= th['conc'][0]:
        return 2
    return 0


def apply_states(down, up, conc, th=None):
    """自常態（前態 0）依序套用 transition。回傳與輸入等長的狀態列。"""
    th = TH if th is None else th
    state, prev = [], 0
    for i in range(len(down)):
        prev = transition(prev, down[i], up[i], conc[i], th)
        state.append(prev)
    return state


def compute(dates, taiex, allg, turnover, conc, start=None, minh=None, th=None):
    """與試行版同一計算。start／minh／th 預設為正式常數，僅供測試縮小暖機。"""
    start = START if start is None else start
    minh = MINHIST if minh is None else minh
    th = TH if th is None else th
    T = len(dates)
    tx = []
    for v in taiex:
        tx.append(v if v else (tx[-1] if tx else None))  # 缺指數沿用較早的值，不看未來
    lag = lambda x, k: [None] * k + x[:-k]

    def ratio(a, b):
        return [a[i] / b[i] - 1 if a[i] and b[i] else None for i in range(T)]

    ret = [None] + [tx[i] / tx[i - 1] - 1 if tx[i] and tx[i - 1] else None for i in range(1, T)]
    r5, r20 = ratio(tx, lag(tx, 5)), ratio(tx, lag(tx, 20))
    vol20 = _roll(ret, 20, _std)
    ma60 = _roll(tx, 60, _mean)
    bias = ratio(tx, ma60)
    t20, t250 = _roll(turnover, 20, _mean), _roll(turnover, 250, _mean)
    turnr = [t20[i] / t250[i] if t20[i] and t250[i] else None for i in range(T)]
    n = allg['n']
    ldr = [allg['ld'][i] / n[i] if n[i] else None for i in range(T)]
    lur = [allg['lu'][i] / n[i] if n[i] else None for i in range(T)]
    ld5, lu5 = _roll(ldr, 5, sum), _roll(lur, 5, sum)
    dd = [(v[3] + v[4] + v[5]) / sum(v) if v and sum(v) else None for v in allg['dd']]
    conc5 = _roll(conc, 5, _mean)
    neg = lambda x: [-v if v is not None else None for v in x]
    raw = dict(nr5=neg(r5), nr20=neg(r20), ld5=ld5, vol=vol20, dd=dd,
               r20=r20, bias=bias, turn=turnr, lu5=lu5, conc=conc5)
    P = {k: _expanding_pr(v, dates, start, minh) for k, v in raw.items()}

    def avg(keys, i):
        vs = [P[k][i] for k in keys if P[k][i] is not None]
        return sum(vs) / len(vs) if len(vs) == len(keys) else None

    down = [avg(['nr5', 'nr20', 'ld5', 'vol', 'dd'], i) for i in range(T)]
    up = [avg(['r20', 'bias', 'turn', 'lu5'], i) for i in range(T)]
    cc = P['conc']
    state = apply_states(down, up, cc, th)
    r = lambda x: [round(v, 3) if v is not None else None for v in x]
    return {'state': state, 'down': r(down), 'up': r(up), 'conc': r(cc), 'th': th, 'rule': RULE_ID}


def _step(down, up, conc):
    return {'down': down, 'up': up, 'conc': conc}


def _below(x):
    return math.nextafter(x, 0.0)


# 可重現邊界案例。steps 為當日分數（未捨入），expected 為逐日狀態。
# 前態由上一日結果帶入，首日的前態為常態 0。
BOUNDARY_CASES = [
    {
        'id': 'enter-down-exact',
        'group': '恰等於進入',
        'desc': '常態，下跌分數恰等於進入 0.85，進入下跌瘋狂',
        'steps': [_step(0.85, 0.0, 0.0)],
        'expected': [-1],
    },
    {
        'id': 'enter-down-just-below',
        'group': '恰等於進入',
        'desc': '下跌分數為進入門檻的下一個較小浮點數，維持常態',
        'steps': [_step(_below(0.85), 0.0, 0.0)],
        'expected': [0],
    },
    {
        'id': 'enter-up-exact',
        'group': '恰等於進入',
        'desc': '常態，上漲分數恰等於進入 0.87，進入上漲瘋狂',
        'steps': [_step(0.0, 0.87, 0.0)],
        'expected': [1],
    },
    {
        'id': 'enter-up-just-below',
        'group': '恰等於進入',
        'desc': '上漲分數恰小於進入門檻，維持常態',
        'steps': [_step(0.0, _below(0.87), 0.0)],
        'expected': [0],
    },
    {
        'id': 'enter-conc-exact',
        'group': '恰等於進入',
        'desc': '常態，集中分數恰等於進入 0.985，進入資金集中炒作',
        'steps': [_step(0.0, 0.0, 0.985)],
        'expected': [2],
    },
    {
        'id': 'enter-conc-just-below',
        'group': '恰等於進入',
        'desc': '集中分數恰小於進入門檻，維持常態',
        'steps': [_step(0.0, 0.0, _below(0.985))],
        'expected': [0],
    },
    {
        'id': 'priority-all-three',
        'group': '同時達標',
        'desc': '常態同時達到三個進入門檻：下跌優先',
        'steps': [_step(0.85, 0.87, 0.985)],
        'expected': [-1],
    },
    {
        'id': 'priority-up-over-conc',
        'group': '同時達標',
        'desc': '常態同時達到上漲與集中、下跌未達：上漲優先',
        'steps': [_step(_below(0.85), 0.87, 0.985)],
        'expected': [1],
    },
    {
        'id': 'priority-only-conc',
        'group': '同時達標',
        'desc': '只有集中達到進入門檻',
        'steps': [_step(0.10, 0.10, 0.985)],
        'expected': [2],
    },
    {
        'id': 'hold-down-exact-exit',
        'group': '既有狀態維持與競合',
        'desc': '已在下跌，下跌分數恰等於退出 0.72，維持下跌',
        'steps': [_step(0.90, 0.0, 0.0), _step(0.72, 0.0, 0.0)],
        'expected': [-1, -1],
    },
    {
        'id': 'hold-down-beats-other-entries',
        'group': '既有狀態維持與競合',
        'desc': '已在下跌且下跌仍達退出，即使上漲與集中都達進入，仍維持下跌（遲滯優先於競合）',
        'steps': [_step(0.90, 0.0, 0.0), _step(0.72, 0.99, 0.99)],
        'expected': [-1, -1],
    },
    {
        'id': 'hold-up-exact-exit',
        'group': '既有狀態維持與競合',
        'desc': '已在上漲，上漲分數恰等於退出 0.80，維持上漲',
        'steps': [_step(0.0, 0.90, 0.0), _step(0.0, 0.80, 0.0)],
        'expected': [1, 1],
    },
    {
        'id': 'hold-up-blocks-down-priority',
        'group': '既有狀態維持與競合',
        'desc': '已在上漲且上漲仍達退出，即使下跌已達進入也不改判下跌',
        'steps': [_step(0.0, 0.90, 0.0), _step(0.99, 0.80, 0.0)],
        'expected': [1, 1],
    },
    {
        'id': 'hold-conc-exact-exit',
        'group': '既有狀態維持與競合',
        'desc': '已在集中，集中分數恰等於退出 0.96，維持集中',
        'steps': [_step(0.0, 0.0, 0.99), _step(0.0, 0.0, 0.96)],
        'expected': [2, 2],
    },
    {
        'id': 'hold-conc-blocks-others',
        'group': '既有狀態維持與競合',
        'desc': '已在集中且集中仍達退出，下跌與上漲達進入仍維持集中',
        'steps': [_step(0.0, 0.0, 0.99), _step(0.99, 0.99, 0.96)],
        'expected': [2, 2],
    },
    {
        'id': 'exit-down-just-below',
        'group': '退出與切換',
        'desc': '已在下跌，下跌分數恰小於退出，且其他未達進入：回到常態',
        'steps': [_step(0.90, 0.0, 0.0), _step(_below(0.72), 0.10, 0.10)],
        'expected': [-1, 0],
    },
    {
        'id': 'exit-up-just-below',
        'group': '退出與切換',
        'desc': '已在上漲，上漲分數恰小於退出，其他未達進入：回到常態',
        'steps': [_step(0.0, 0.90, 0.0), _step(0.10, _below(0.80), 0.10)],
        'expected': [1, 0],
    },
    {
        'id': 'exit-conc-just-below',
        'group': '退出與切換',
        'desc': '已在集中，集中分數恰小於退出，其他未達進入：回到常態',
        'steps': [_step(0.0, 0.0, 0.99), _step(0.10, 0.10, _below(0.96))],
        'expected': [2, 0],
    },
    {
        'id': 'exit-down-switch-up',
        'group': '退出與切換',
        'desc': '已在下跌，同日跌破退出且上漲達到進入：直接改為上漲',
        'steps': [_step(0.90, 0.0, 0.0), _step(_below(0.72), 0.87, 0.99)],
        'expected': [-1, 1],
    },
    {
        'id': 'exit-down-switch-conc',
        'group': '退出與切換',
        'desc': '已在下跌，同日跌破退出、上漲未達、集中達到進入：改為集中',
        'steps': [_step(0.90, 0.0, 0.0), _step(_below(0.72), 0.10, 0.985)],
        'expected': [-1, 2],
    },
    {
        'id': 'exit-up-switch-down',
        'group': '退出與切換',
        'desc': '已在上漲，同日跌破退出且下跌達到進入：改為下跌（進入優先序）',
        'steps': [_step(0.0, 0.90, 0.0), _step(0.85, _below(0.80), 0.99)],
        'expected': [1, -1],
    },
    {
        'id': 'exit-conc-switch-down',
        'group': '退出與切換',
        'desc': '已在集中，同日跌破退出且下跌達到進入：改為下跌',
        'steps': [_step(0.0, 0.0, 0.99), _step(0.85, 0.10, _below(0.96))],
        'expected': [2, -1],
    },
    {
        'id': 'exit-conc-switch-up',
        'group': '退出與切換',
        'desc': '已在集中，同日跌破退出、下跌未達、上漲達到進入：改為上漲',
        'steps': [_step(0.0, 0.0, 0.99), _step(0.10, 0.87, _below(0.96))],
        'expected': [2, 1],
    },
    {
        'id': 'stay-sequence',
        'group': '退出與切換',
        'desc': '進入下跌、中間仍高於退出而維持、再低於退出且無其他進入而回常態',
        'steps': [_step(0.85, 0.0, 0.0), _step(0.90, 0.50, 0.50), _step(0.50, 0.10, 0.10)],
        'expected': [-1, -1, 0],
    },
    {
        'id': 'warmup-all-none',
        'group': '暖機不足與缺值',
        'desc': '分數皆缺（暖機或無資料），前態常態，維持常態',
        'steps': [_step(None, None, None), _step(None, None, None)],
        'expected': [0, 0],
    },
    {
        'id': 'missing-exits-down',
        'group': '暖機不足與缺值',
        'desc': '已在下跌，當日下跌分數缺值且其他未達進入：退出為常態',
        'steps': [_step(0.90, 0.0, 0.0), _step(None, 0.10, 0.10)],
        'expected': [-1, 0],
    },
    {
        'id': 'missing-down-allows-up',
        'group': '暖機不足與缺值',
        'desc': '已在下跌，下跌分數缺值且上漲達到進入：退出並改為上漲',
        'steps': [_step(0.90, 0.0, 0.0), _step(None, 0.87, 0.0)],
        'expected': [-1, 1],
    },
    {
        'id': 'missing-up-from-up',
        'group': '暖機不足與缺值',
        'desc': '已在上漲，上漲分數缺值且其他未達進入：退出為常態',
        'steps': [_step(0.0, 0.90, 0.0), _step(0.10, None, 0.10)],
        'expected': [1, 0],
    },
    {
        'id': 'missing-conc-from-conc',
        'group': '暖機不足與缺值',
        'desc': '已在集中，集中分數缺值且其他未達進入：退出為常態',
        'steps': [_step(0.0, 0.0, 0.99), _step(0.10, 0.10, None)],
        'expected': [2, 0],
    },
    {
        'id': 'missing-all-from-abnormal',
        'group': '暖機不足與缺值',
        'desc': '已在上漲，三項分數都缺：退出為常態',
        'steps': [_step(0.0, 0.90, 0.0), _step(None, None, None)],
        'expected': [1, 0],
    },
    {
        'id': 'partial-none-no-enter',
        'group': '暖機不足與缺值',
        'desc': '上漲與集中缺值，下跌未達進入：常態',
        'steps': [_step(0.50, None, None)],
        'expected': [0],
    },
    {
        'id': 'enter-down-others-none',
        'group': '暖機不足與缺值',
        'desc': '上漲與集中缺值，下跌恰達進入：仍進入下跌',
        'steps': [_step(0.85, None, None)],
        'expected': [-1],
    },
]


def boundary_rows(th=None):
    """跑完全部邊界案例。每一日一列：輸入、前一狀態、預期、實際。"""
    th = TH if th is None else th
    rows = []
    ok = True
    for case in BOUNDARY_CASES:
        prev = 0
        for i, step in enumerate(case['steps']):
            actual = transition(prev, step['down'], step['up'], step['conc'], th)
            exp = case['expected'][i]
            match = actual == exp
            ok = ok and match
            rows.append({
                'id': case['id'],
                'group': case['group'],
                'desc': case['desc'],
                'day': i + 1,
                'prev': prev,
                'down': step['down'],
                'up': step['up'],
                'conc': step['conc'],
                'expected': exp,
                'actual': actual,
                'match': match,
            })
            prev = actual
    return {'rule': RULE_ID, 'pass': ok, 'rows': rows}
