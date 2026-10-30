"""市場非常態（瘋狂）判定。

現行規則 2026-10-30（價格規則，Ed 2026-10-30 指定方向：抓劇烈快速下跌／急漲波段、盡量抓到頂部，
搭配非常態期間累積漲跌；命中率不是主要標準）：

  下跌瘋狂：加權指數收盤 <= 近 15 日（含當日）最高收盤 ×（1−9%）時進入；
            期間追蹤最低收盤，收盤 >= 該最低 ×（1+6%）時解除。
  上漲瘋狂：收盤 >= 近 40 日（含當日）最低收盤 ×（1+20%）時進入；
            期間追蹤最高收盤，收盤 <= 該最高 ×（1−5%）時解除。
  解除當日為常態，不在同日進入另一狀態；常態下同時達標以下跌優先。
  窗口只用 2005-01-01 起、至當日（含）的收盤；指數缺值沿用前一筆。
  「資金集中炒作」不再是狀態（Ed 2026-10-30 同意）；集中分數仍計算，只供參考。
  舊版百分位分數 down／up 仍寫出供對照，不參與判定。

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
        'kind': 'score',
        'start': START,
        'minhist': MINHIST,
        'priority': ['down', 'up', 'conc'],
    },
    {
        'id': '2026-10-30',
        'effective': '2026-10-30',
        'kind': 'price',
        'note': 'Ed 2026-10-30 改為價格規則（下跌 15 日高回落 9%、反彈 6% 解除；上漲 40 日低上漲 20%、回落 5% 解除），取消資金集中狀態。',
        'th': {'down': (0.09, 0.06), 'up': (0.20, 0.05)},
        'win': {'down': 15, 'up': 40},
        'start': START,
        'priority': ['down', 'up'],
    },
]
TH = TH_VERSIONS[-1]['th']
WIN = TH_VERSIONS[-1]['win']
RULE_ID = TH_VERSIONS[-1]['id']
STATE_NAME = {-1: '下跌瘋狂', 1: '上漲瘋狂', 2: '資金集中炒作（舊版）', 0: '常態'}


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


def transition_v1(prev, dv, uv, cv, th=None):
    """由前一狀態與當日三個分數得到當日狀態。分數 None 視為未達該側門檻。

    順序：
      1. 若前態為非常態，且該狀態自己的分數仍 >= 退出門檻，維持前態（不看其他分數）。
      2. 否則先回到常態，再依下跌、上漲、集中檢查進入門檻（>=）。先符合者勝出。
    因此：遲滯優先於「同時達標」的優先序；退出與改入另一狀態可以發生在同一天。
    """
    th = TH_VERSIONS[0]['th'] if th is None else th
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


def apply_states_v1(down, up, conc, th=None):
    """舊版 2026-10-29：自常態依序套用 transition_v1。"""
    th = TH_VERSIONS[0]['th'] if th is None else th
    state, prev = [], 0
    for i in range(len(down)):
        prev = transition_v1(prev, down[i], up[i], conc[i], th)
        state.append(prev)
    return state


def price_states(tx, i0, th=None, win=None):
    """價格規則狀態機。tx 為已沿用前值的收盤；i0 為 2005-01-01 起第一個索引。

    回傳 (state, dd, ru)：dd＝收盤相對近 win['down'] 日（含當日）最高收盤的漲跌，
    ru＝相對近 win['up'] 日最低收盤的漲跌。窗口不足或在 i0 之前為 None。
    比較一律用乘法（收盤 <= 高點×(1−門檻)），避免除法浮點誤差。
    """
    th = TH if th is None else th
    win = WIN if win is None else win
    T = len(tx)
    (din, dout), (uin, uout) = th['down'], th['up']
    wd, wu = win['down'], win['up']
    state, dd, ru = [0] * T, [None] * T, [None] * T
    mode, ext = 0, None
    for i in range(max(0, i0), T):
        p = tx[i]
        if p is None:
            state[i] = mode
            continue
        hi = lo = None
        if i - i0 >= wd and all(v is not None for v in tx[i - wd:i + 1]):
            hi = max(tx[i - wd:i + 1])
            dd[i] = p / hi - 1
        if i - i0 >= wu and all(v is not None for v in tx[i - wu:i + 1]):
            lo = min(tx[i - wu:i + 1])
            ru[i] = p / lo - 1
        if mode == -1:
            ext = min(ext, p)
            if p >= ext * (1 + dout):
                mode = 0
        elif mode == 1:
            ext = max(ext, p)
            if p <= ext * (1 - uout):
                mode = 0
        elif hi is not None and p <= hi * (1 - din):
            mode, ext = -1, p
        elif lo is not None and p >= lo * (1 + uin):
            mode, ext = 1, p
        state[i] = mode
    return state, dd, ru


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
    i0 = next((i for i, d in enumerate(dates) if d >= start), T)
    state, dd, ru = price_states(tx, i0, th, WIN)
    r = lambda x, k=3: [round(v, k) if v is not None else None for v in x]
    return {'state': state, 'dd': r(dd, 4), 'ru': r(ru, 4), 'down': r(down), 'up': r(up), 'conc': r(cc),
            'th': th, 'win': WIN, 'rule': RULE_ID}


def _step(down, up, conc):
    return {'down': down, 'up': up, 'conc': conc}


def _below(x):
    return math.nextafter(x, 0.0)


# 可重現邊界案例。steps 為當日分數（未捨入），expected 為逐日狀態。
# 前態由上一日結果帶入，首日的前態為常態 0。
BOUNDARY_CASES_V1 = [
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


def _pc(pid, group, desc, prices, expected):
    return {'id': pid, 'group': group, 'desc': desc, 'prices': prices, 'expected': expected}


_W3 = {'down': 3, 'up': 3}
_D_IN = 100 * (1 - 0.09)
_U_IN = 100 * (1 + 0.20)
# 價格規則邊界案例（窗口縮成 3 日以便手算）。prices 為逐日收盤，expected 為逐日狀態。
BOUNDARY_CASES = [
    _pc('down-enter-exact', '恰等於進入', '3 日高 100，收盤恰等於 100×0.91，進入下跌', [100, 100, 100, _D_IN], [0, 0, 0, -1]),
    _pc('down-enter-just-above', '恰等於進入', '收盤比 100×0.91 高一個浮點數，維持常態', [100, 100, 100, math.nextafter(_D_IN, 1e9)], [0, 0, 0, 0]),
    _pc('up-enter-exact', '恰等於進入', '3 日低 100，收盤恰等於 100×1.2，進入上漲', [100, 100, 100, _U_IN], [0, 0, 0, 1]),
    _pc('up-enter-just-below', '恰等於進入', '收盤比 100×1.2 低一個浮點數，維持常態', [100, 100, 100, math.nextafter(_U_IN, 0)], [0, 0, 0, 0]),
    _pc('warmup', '暖機不足', '窗口未滿（前 3 日）即使大跌也不判定', [100, 50, 40], [0, 0, 0]),
    _pc('down-hold-track-low', '維持與解除', '進入後續跌，低點更新；反彈未達低點×1.06 維持', [100, 100, 100, 90, 80, 84], [0, 0, 0, -1, -1, -1]),
    _pc('down-exit-exact', '維持與解除', '低點 80，收盤恰等於 80×1.06，解除為常態', [100, 100, 100, 90, 80, 80 * 1.06], [0, 0, 0, -1, -1, 0]),
    _pc('down-exit-no-same-day-entry', '維持與解除', '解除當日為常態；隔日收盤再低於 3 日高×0.91 則重新進入', [100, 100, 100, 90, 80, 85, 81], [0, 0, 0, -1, -1, 0, -1]),
    _pc('up-exit-exact', '維持與解除', '高點 130，收盤恰等於 130×0.95，解除', [100, 100, 100, 120, 130, 130 * (1 - 0.05)], [0, 0, 0, 1, 1, 0]),
    _pc('up-hold', '維持與解除', '回落未達 5% 維持上漲', [100, 100, 100, 120, 130, 124], [0, 0, 0, 1, 1, 1]),
    _pc('exit-day-then-priority', '同時達標與競合', '第 6 日解除下跌（同日上漲條件也成立，但解除日不進入）；第 7 日下跌與上漲同時成立，下跌優先', [100, 100, 100, 90, 60, 75, 75], [0, 0, 0, -1, -1, 0, -1]),
]


def boundary_rows(th=None):
    """跑完全部價格規則邊界案例。每一日一列：收盤、前一狀態、預期、實際。"""
    th = TH if th is None else th
    rows, ok = [], True
    for case in BOUNDARY_CASES:
        st, dd, ru = price_states(case['prices'], 0, th, _W3)
        prev = 0
        for i, exp in enumerate(case['expected']):
            match = st[i] == exp
            ok = ok and match
            rows.append({'id': case['id'], 'group': case['group'], 'desc': case['desc'], 'day': i + 1,
                         'prev': prev, 'price': case['prices'][i], 'dd': dd[i], 'ru': ru[i],
                         'expected': exp, 'actual': st[i], 'match': match})
            prev = st[i]
    return {'rule': RULE_ID, 'pass': ok, 'rows': rows}
