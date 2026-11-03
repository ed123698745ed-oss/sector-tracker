"""融資觀察分頁：大盤與個股估算融資維持率，輸出 docs/margin.json 與 docs/margin/s/代號.csv。

只供觀察市場，不是交易訊號；個股為公開資料模型估算，不是券商實際整戶擔保維持率。

資料（全部為官方公開資料，原始檔存 archive/raw）
  融資：證交所 MI_MARGN（twse_margin）、櫃買 margin/balance（tpex_margin），單位張
  價格：證交所 MI_INDEX（twse）、櫃買 afterTrading/otc（tpex）的收盤價、成交股數、成交金額
  日均價＝成交金額 ÷ 成交股數；無成交日不更新價格，沿用最近一次收盤（標記為沿用）

大盤維持率（上市、上櫃分開算，不是個股平均）
  主數字（對齊財經M平方，Ed 2026-11-01 指定）：Σ（普通股融資今日餘額張數 × 1000 × 當日收盤價）÷ 該市場官方融資金額餘額
    分子只算普通股（4 碼、首碼非 0，不含 ETF），分母為官方全部融資金額。2019～2025 年 14 個 M平方 對照日中
    7 個差距在 ±1.5 個百分點內；2018 年 3 個對照日則與「全部證券」口徑完全相同，2022/9～10 差約 10 點，原因不明
  參考數字 maint_all：分子含 ETF 等所有可融資證券
  分母：上市「信用交易統計」融資金額(仟元)今日餘額；上櫃表尾「融資金(仟元)」資餘額欄
  當日無收盤價者用最近一次收盤（fallback 清單一併輸出）

期間：大盤與近 30 日追價者崩跌家數自最早原始檔起算（上市 2004-02、上櫃 2007-07）；
      全體平均批次模型與個股歷史 CSV 自 START 起算（Ed 2026-11-01 同意延伸大盤與崩跌觀察）

個股估算（模型 MR01，起算日 START）
  1. 逐日重播融資庫存（批次法）：每日淨融資買進為一個批次，成本＝當日均價
  2. 當日沖銷：同日融資買進與融資賣出先互抵，視為當日進出、不進庫存
  3. 出場順序（追繳優先）：當日淨賣出＋現金償還，先從估算維持率已低於 130% 的批次移出（成本高者先），
     其餘按比例自各批次移出
  4. 期初庫存：起算日已有的融資餘額為一個批次，成本設為起算日前 60 個交易日日均價的平均；同時以這 60 日的
     最低／最高日均價各算一次（成本敏感度）
  5. 統一股份基準：交易所公布的「前日餘額」與前一日「今日餘額」不同時，先查股數事件（2026-11-03 檢驗報告第 1、2 項）：
     - 差距 ≤ 2 張或 < 0.5%：不換算（當日終了再與今日餘額對齊）
     - 同日有股數事件（上市：證交所減資恢復買賣 TWTAUU、變更面額恢復買賣 TWTB8U、除權息／減資參考價表；
       上櫃：收盤行情「發行股數」較該股前一次出現時變動 ≥ 0.5%）：視為股數基準改變，比例 r＝前日餘額÷前一日今日餘額，
       各批次張數 × r、成本 ÷ r；r 不在 1/20～20 之間則判為異常
     - 查無事件、r 在 2/3～1.5 之間：不換算，差額當作當日買進（以當日均價入庫）或償還（按比例移出）
     - 查無事件、r 超出 2/3～1.5（如換股合併）：判為異常，排除於排行
     - ETF 等非普通股沒有事件表（上櫃 ETF 發行單位每日變動），沿用依比例換算；不列入排行，只影響官方校準的模型總額
     觸發的事件與異常寫入 margin.json 的 basis
  6. 官方校準：每日每市場 k＝官方融資金額 ÷ Σ（批次張數 × 1000 × 0.6 × 批次成本），個股成本 × k，
     使模型總額等於官方總額（2026-10-30 驗證：未校準前 k 約 1.01～1.02，代表模型總額已接近官方）
  7. 估算維持率＝收盤價 ÷（0.6 × 校準後平均成本）× 100
  8. 融資使用率＝融資今日餘額 ÷ 融資限額（上市「次一營業日限額」、上櫃「資限額」）× 100
  排行與統計只納入通過檢查的普通股（4 碼、首碼非 0）：
    - 有效歷史（起算後有融資資料的交易日）≥ 120 日
    - 期初庫存占目前餘額 ≤ 35%
    - 成本敏感度（最低／最高期初成本算出的維持率差）≤ 10 個百分點
    - 融資餘額 ≥ 10 張、當日有收盤價、股數基準沒有異常

已知限制
  - 批次法、當日沖銷互抵與追繳優先都是假設；實際各投資人成本、券商融資成數（上市上櫃一般 60%，
    個別股票或券商可能不同）與整戶擔保都不同。整戶擔保下，個股估算維持率可能長期低於 100%
  - 簡化指標，不是券商整戶擔保維持率：未含融券、保證金與抵繳品；未做除權息前六個營業日的擔保品市值調整；
    無收盤價時一律沿用最近收盤（法規另有報價與開盤基準等計價規則）；現金股利不調整成本、配股不加計擔保品
"""
import datetime, glob, gzip, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'archive', 'raw')
OUT_JSON = os.environ.get('MR_OUT', os.path.join(ROOT, 'docs')) + '/margin.json'
OUT_DIR = os.environ.get('MR_OUT', os.path.join(ROOT, 'docs')) + '/margin/s'
START = '20250102'   # 模型起算日（固定，起算日改變會改寫全部歷史，須經 Ed 確認）
MODEL = 'MR01'
RATIO = 0.6
MIN_DAYS, MAX_INIT, MAX_SENS, MIN_BAL = 120, 35.0, 10.0, 10
BASIS_MIN_LOTS, BASIS_MIN_PCT, BASIS_MAX_FLOW = 2, 0.005, 1.5   # 前日餘額不連續：忽略門檻（張、比例）與無事件時可當買賣的最大比例
NET_DAYTRADE = os.environ.get('MR_NET', '1') == '1'
TPEX_PX_START = '20070702'   # 上櫃收盤原始檔有內容的第一天（之前的檔案為空）
RECENT_N = 30   # 近期追價者窗口（交易日）；以三竹 7 檔×13 日校準選定
FORCED_FIRST, CALL = os.environ.get('MR_FORCED', '1') == '1', 130.0
ORDER = os.environ.get('MR_ORDER', 'prop')   # 其餘出場順序：prop 按比例、fifo 舊先、lifo 新先
COMMON = re.compile(r'^(?!91)[1-9]\d{3}$')   # 普通股：4 碼、首碼非 0，排除 91 開頭的存託憑證（TDR）；與 wh_prices.py 同口徑


def num(s):
    try:
        return float(str(s).replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def load(src, ds):
    p = os.path.join(RAW, src, f'{ds}.json.gz')
    if not os.path.exists(p):
        return None
    with gzip.open(p, 'rt', encoding='utf-8') as f:
        return json.load(f)


def prices_twse(j):
    """→ {代號: (名稱, 收盤, 日均價)}"""
    out = {}
    for t in (j or {}).get('tables', []):
        if '每日收盤行情' in (t.get('title') or ''):
            f = t['fields']
            ic, iv, ia = f.index('收盤價'), f.index('成交股數'), f.index('成交金額')
            for r in t['data']:
                c, v, a = num(r[ic]), num(r[iv]), num(r[ia])
                if c:
                    out[r[0].strip()] = (r[1].strip(), c, a / v if v and a else c)
    return out


def prices_tpex(j):
    out = {}
    for t in (j or {}).get('tables', []):
        f = [x.strip() for x in t.get('fields', [])]
        if '收盤' in f and '成交股數' in f:
            ic, iv, ia = f.index('收盤'), f.index('成交股數'), f.index('成交金額(元)')
            for r in t['data']:
                c, v, a = num(r[ic]), num(r[iv]), num(r[ia])
                if c:
                    out[r[0].strip()] = (r[1].strip(), c, a / v if v and a else c)
    return out


def margin_twse(j):
    """→ (官方融資金額元, {代號: dict})"""
    loan, rows = None, {}
    for t in j.get('tables', []):
        title = t.get('title') or ''
        if '信用交易統計' in title:
            for r in t['data']:
                if r[0].startswith('融資金額'):
                    loan = num(r[5]) * 1000
        elif '融資融券彙總' in title:
            for r in t['data']:
                rows[r[0].strip()] = dict(name=r[1].strip(), buy=num(r[2]) or 0, sell=num(r[3]) or 0,
                                          repay=num(r[4]) or 0, prev=num(r[5]) or 0, bal=num(r[6]) or 0,
                                          limit=num(r[7]))
    return loan, rows


def margin_tpex(j):
    loan, rows = None, {}
    t = j['tables'][0]
    for r in t.get('summary') or []:
        if '融資金' in str(r[1]):
            loan = num(r[6]) * 1000
    for r in t['data']:
        rows[r[0].strip()] = dict(name=r[1].strip(), prev=num(r[2]) or 0, buy=num(r[3]) or 0, sell=num(r[4]) or 0,
                                  repay=num(r[5]) or 0, bal=num(r[6]) or 0, limit=num(r[9]))
    return loan, rows


def trading_days():
    """有上市融資原始檔與上市收盤原始檔的日子（資料日以檔名＝已檢查過的內文日期為準）。
    上櫃另在當日檢查：有上櫃融資與上櫃收盤原始檔才計算（上櫃融資 2007-01 起、上櫃收盤 2007-07 起）"""
    a = {os.path.basename(p)[:8] for p in glob.glob(f'{RAW}/twse_margin/*.json.gz')}
    return sorted(d for d in a if os.path.exists(f'{RAW}/twse/{d}.json.gz'))


def taiex_fmtqik(ds, _c={}):
    """2009 年以前 MI_INDEX 無指數表：改用證交所 FMTQIK 月表的加權指數收盤（同 wh_build.py）"""
    ym = ds[:6]
    if ym not in _c:
        _c[ym] = {}
        fp = os.path.join(RAW, 'twse_fmtqik', ym + '.json')
        if os.path.exists(fp):
            for r in json.load(open(fp)).get('data') or []:
                a, b, c = r[0].strip().split('/')
                _c[ym]['%d%s%s' % (int(a) + 1911, b, c)] = num(r[4])
    return _c[ym].get(ds)


def tpex_shares(j):
    """上櫃收盤行情的發行股數 → {代號: 股數}（上櫃股數事件偵測用）"""
    out = {}
    for t in (j or {}).get('tables', []):
        f = [x.strip() for x in t.get('fields', [])]
        if '發行股數' in f and '收盤' in f:
            i = f.index('發行股數')
            for r in t['data']:
                v = num(r[i])
                if v:
                    out[r[0].strip()] = v
    return out


def twse_basis_events():
    """上市股數事件 {(代號, 日期)}：減資恢復買賣 TWTAUU、變更面額恢復買賣 TWTB8U（archive/raw/twse_events），
    加上每日更新的除權息／減資參考價表 data/exright_twse.json（含 TWTAUU）。後者混有除權息，只用來補
    twse_events 尚未涵蓋的日子（該目錄由 wh_monthly 每月、whext 手動更新）"""
    ev = set()
    for fp in glob.glob(os.path.join(RAW, 'twse_events', 'TWTAUU_*.json')) + glob.glob(os.path.join(RAW, 'twse_events', 'TWTB8U_*.json')):
        for r in json.load(open(fp)).get('data') or []:
            m = re.match(r'(\d+)\D+(\d+)\D+(\d+)', str(r[0]))
            if m:
                ev.add((str(r[1]).strip(), '%d%02d%02d' % (int(m[1]) + 1911, int(m[2]), int(m[3]))))
    covered = max((d for _, d in ev), default='')
    fp = os.path.join(ROOT, 'data', 'exright_twse.json')
    if os.path.exists(fp):
        for ds, v in json.load(open(fp)).items():
            if ds > covered:
                ev.update((c, ds) for c in v)
    return ev


def price_days_before(ds, n):
    """ds 之前 n 個有上市收盤原始檔的日子（期初成本用）"""
    ds_all = sorted(os.path.basename(p)[:8] for p in glob.glob(f'{RAW}/twse/*.json.gz'))
    prev = [d for d in ds_all if d < ds]
    return prev[-n:]


class Pos:
    __slots__ = ('mkt', 'name', 'inv', 'cost', 'cost_lo', 'cost_hi', 'init', 'days', 'bad', 'last_bal', 'hist',
                 'last_close', 'stale', 'lots', 'win', 'rdays', 'fac', 'bh', 'started')

    def __init__(self, mkt, name):
        self.mkt, self.name = mkt, name
        self.inv = 0.0
        self.cost = self.cost_lo = self.cost_hi = None
        self.init = 0.0       # 期初庫存剩餘張數
        self.days = 0
        self.bad = None
        self.last_bal = None
        self.hist = []
        self.last_close = None
        self.stale = False
        self.win = []    # 近期淨融資買進 [(張數, 金額)]，最多 RECENT_N 日
        self.rdays = 0
        self.fac = 1.0   # 累積張數基準係數
        self.bh = {}     # 日期 → (今日餘額, 當時基準係數)，含零餘額日
        self.started = False   # 全體平均模型是否已起算
        self.lots = []   # 批次 [張數, 成本, 期初低成本, 期初高成本, 是否期初]


def main():
    days = trading_days()   # 大盤與近期口徑自最早資料起算；全體平均庫存模型自 START 起算
    if not days or days[-1] < START:
        raise SystemExit('沒有融資原始檔')
    start_day = next(d for d in days if d >= START)
    # 期初成本：起算日前 60 個交易日的日均價
    pre = price_days_before(start_day, 60)
    pre_avg = {}
    for d in pre:
        for src, fn in (('twse', prices_twse), ('tpex', prices_tpex)):
            for c, (_, _, a) in fn(load(src, d)).items():
                pre_avg.setdefault(c, []).append(a)

    pos = {}
    market = []
    crash = {}     # 日期 → [近期口徑樣本數, <130 家數, <140 家數, <130 個股融資餘額合計張數]
    taiex = {}
    last_px = {}   # 代號 → (日期, 收盤)；以起算前約一年的真實收盤初始化（Eve F2）
    ev_twse = twse_basis_events()
    tp_sh = {}      # 上櫃代號 → 最近一次出現的發行股數
    basis_log = []  # 前日餘額不連續的處理紀錄（起算日後、換算或異常、或差距 ≥ 2%）
    for d in price_days_before(days[0], 250):
        for src, fn in (('twse', prices_twse), ('tpex', prices_tpex)):
            for c, v in fn(load(src, d)).items():
                last_px[c] = (d, v[1])
    for di, ds in enumerate(days):
        full = ds >= START   # 全體平均（批次法）只在起算日後執行
        px = {}
        sh_event = set()   # 當日上櫃發行股數變動的代號
        for src, fn in (('twse', prices_twse), ('tpex', prices_tpex)):
            raw = load(src, ds)
            if raw is None:
                continue
            if src == 'twse':
                for t in raw.get('tables', []):
                    if (t.get('title') or '').endswith('價格指數(臺灣證券交易所)'):
                        for rr in t['data']:
                            if rr[0] in ('發行量加權股價指數', '加權股價指數'):
                                taiex[ds] = num(rr[1])
                if ds not in taiex:
                    taiex[ds] = taiex_fmtqik(ds)
            for c, v in fn(raw).items():
                px[c] = v
                last_px[c] = (ds, v[1])
            if src == 'tpex':
                sh_event = set()
                for c, v in tpex_shares(raw).items():
                    if c in tp_sh and abs(v / tp_sh[c] - 1) >= BASIS_MIN_PCT:
                        sh_event.add(c)
                    tp_sh[c] = v
        for mkt, src, parse in (('TWSE', 'twse_margin', margin_twse), ('TPEX', 'tpex_margin', margin_tpex)):
            if mkt == 'TPEX' and (ds < TPEX_PX_START or not (os.path.exists(f'{RAW}/tpex_margin/{ds}.json.gz') and os.path.exists(f'{RAW}/tpex/{ds}.json.gz'))):
                continue
            loan, rows = parse(load(src, ds))
            coll = coll_stk = est_loan = 0.0
            bal_total = 0.0
            fallback = []
            unpriced = []   # 有餘額卻完全查無價格（不計入市值，明列）
            todo = []
            for c, r in rows.items():
                p = pos.get(c)
                if p is None:
                    p = pos[c] = Pos(mkt, r['name'])
                p.name, p.mkt = r['name'], mkt   # 市場依當日來源更新（Eve F1：轉上市／轉上櫃）
                bal = r['bal']
                # 前日餘額不連續（說明第 5 點）：有股數事件才換算基準，否則差額當買進／償還，大幅跳動判異常
                basis, flow_in = None, 0.0
                if p.last_bal is not None:
                    diff = r['prev'] - p.last_bal
                    if abs(diff) > BASIS_MIN_LOTS and abs(diff) >= BASIS_MIN_PCT * p.last_bal:
                        k = r['prev'] / p.last_bal if p.last_bal > 0 and r['prev'] > 0 else None
                        # ETF 等非普通股不在事件表、上櫃 ETF 發行單位每日變動：沿用原做法一律依比例換算（不列入排行，只影響校準總額）
                        has_ev = not COMMON.match(c) or ((c, ds) in ev_twse if mkt == 'TWSE' else c in sh_event)
                        if k and has_ev:
                            basis = 'event' if 1 / 20 <= k <= 20 else 'bad'
                        elif k and not (1 / BASIS_MAX_FLOW <= k <= BASIS_MAX_FLOW):
                            basis = 'bad'
                        else:
                            basis = 'flow'
                        if basis == 'event':
                            # 張數基準係數（Eve F3）：供跨分割比較餘額與近期口徑張數
                            p.fac *= k
                            p.win = [(q * k, v) for q, v in p.win]
                        if full and p.lots:
                            if basis == 'event':
                                for L in p.lots:
                                    L[0] *= k; L[1] /= k; L[2] /= k; L[3] /= k
                            elif basis == 'bad':
                                p.bad = (f'{ds} 前日餘額 {r["prev"]:g} 張與前一日 {p.last_bal:g} 張不符、比例 {k:.3f}' if k else f'{ds} 前日餘額不連續') + \
                                        ('，股數基準比例異常' if has_ev else '，查無減資／分割事件（疑合併）')
                            elif diff < 0:
                                tot = sum(L[0] for L in p.lots)
                                if tot > 0:
                                    for L in p.lots:
                                        L[0] *= max(r['prev'], 0) / tot
                            else:
                                flow_in = diff
                        elif full and basis == 'flow' and diff > 0 and p.started:   # 起算日當天由期初庫存涵蓋
                            flow_in = diff
                        if full and COMMON.match(c) and (basis != 'flow' or (k and abs(k - 1) >= 0.02)):
                            basis_log.append(dict(date=ds, s=c, m=mkt, last=p.last_bal, prev=r['prev'],
                                                  k=None if k is None else round(k, 4), act=basis))
                name_px = px.get(c)
                avg = name_px[2] if name_px else None
                close = name_px[1] if name_px else (last_px.get(c) or (None, None))[1]
                if not name_px and bal > 0:
                    if close is not None:
                        fallback.append(dict(symbol=c, balance=bal, close=close, price_date=last_px[c][0]))
                    else:
                        unpriced.append(dict(symbol=c, balance=bal))
                p.stale = name_px is None
                if full and not p.started and r['prev'] > 0:
                    # 期初庫存：起算日已有的餘額，或起算後才第一次出現就已有前日餘額（轉上市等），成本未知
                    hist = pre_avg.get(c) if ds == start_day else None
                    if hist:
                        base, lo, hi = sum(hist) / len(hist), min(hist), max(hist)
                    else:
                        base = lo = hi = avg or close
                    if base:
                        p.lots = [[r['prev'], base, lo, hi, 1]]
                    else:   # 完全查無價格：期初庫存成本未知，不能讓「期初 ≤35%」檢查因無期初批次而被繞過（檢驗報告次要項目）
                        p.bad = f'{ds} 期初庫存 {r["prev"]:g} 張成本未知'
                        p.started = True
                # 當日沖銷：同日融資買進與融資賣出先互抵（視為當日進出，不進庫存），只有淨買進才以當日均價入庫
                net = min(r['buy'], r['sell']) if NET_DAYTRADE else 0
                buy, out = r['buy'] - net, r['sell'] - net + r['repay']
                # 近期追價者：最近 RECENT_N 個交易日淨融資買進（扣當日沖銷）的加權均價
                p.win.append((buy, buy * avg) if buy > 0 and avg else (0.0, 0.0))
                if len(p.win) > RECENT_N:
                    p.win.pop(0)
                p.rdays += 1
                if full:
                    p.started = True
                if full and flow_in > 0 and (avg or close):
                    q = avg or close   # 查無事件的前日餘額增加：視為當日買進
                    p.lots.append([flow_in, q, q, q, 0])
                if full and buy > 0 and (avg or close):
                    q = avg or close
                    p.lots.append([buy, q, q, q, 0])
                if full and out > 0 and p.lots:
                    # 追繳優先：估算維持率已低於 130% 的批次先出場（成本高者先），其餘按比例移出
                    if close and FORCED_FIRST:
                        for L in sorted((L for L in p.lots if close / (RATIO * L[1]) * 100 < CALL), key=lambda L: -L[1]):
                            x = min(L[0], out); L[0] -= x; out -= x
                            if out <= 0:
                                break
                    tot = sum(L[0] for L in p.lots)
                    if out > 0 and tot > 0 and ORDER == 'prop':
                        keep = max(tot - out, 0) / tot
                        for L in p.lots:
                            L[0] *= keep
                    elif out > 0 and tot > 0:   # fifo：舊批次先出；lifo：新批次先出
                        for L in (p.lots if ORDER == 'fifo' else reversed(p.lots)):
                            x = min(L[0], out); L[0] -= x; out -= x
                            if out <= 0:
                                break
                    p.lots = [L for L in p.lots if L[0] > 1e-9]
                # 與交易所今日餘額對齊（正常情況恆等式成立，差異只來自上面的未知成本或四捨五入）
                tot = sum(L[0] for L in p.lots)
                if bal <= 0:
                    p.lots = []
                elif tot > 0 and abs(tot - bal) > 1e-6:
                    for L in p.lots:
                        L[0] *= bal / tot
                if full and len(p.lots) > 400:   # 合併時間相鄰、成本相近的批次，控制記憶體（保留先後順序）
                    m = []
                    for L in p.lots:
                        if m and not L[4] and not m[-1][4] and abs(L[1] / m[-1][1] - 1) < 0.005:
                            n = m[-1][0] + L[0]; m[-1][1] = (m[-1][1] * m[-1][0] + L[1] * L[0]) / n
                            m[-1][2] = m[-1][3] = m[-1][1]; m[-1][0] = n
                        else:
                            m.append(L)
                    p.lots = m
                tot = sum(L[0] for L in p.lots)
                if tot > 0:
                    p.cost = sum(L[0] * L[1] for L in p.lots) / tot
                    p.cost_lo = sum(L[0] * L[2] for L in p.lots) / tot
                    p.cost_hi = sum(L[0] * L[3] for L in p.lots) / tot
                    p.init = sum(L[0] for L in p.lots if L[4])
                else:
                    p.cost = p.cost_lo = p.cost_hi = None; p.init = 0
                p.inv = bal
                if bal > 0:
                    p.days += 1 if p.cost is not None else 0
                p.last_bal = bal
                p.bh[ds] = (bal, p.fac)
                if len(p.bh) > 25:   # 只需近 20 日與 T−5
                    del p.bh[next(iter(p.bh))]
                # 大盤
                if bal > 0 and close is not None:
                    coll += bal * 1000 * close
                    if COMMON.match(c):
                        coll_stk += bal * 1000 * close
                bal_total += bal
                if bal > 0 and p.cost:
                    est_loan += bal * 1000 * p.cost * RATIO
                # 個股歷史（只記普通股、有部位的日子）；校準係數待全市場加總後套用
                if COMMON.match(c) and bal > 0 and p.cost and close and full:
                    usage = bal / r['limit'] * 100 if r['limit'] else None
                    todo.append((p, close, bal, bal - r['prev'], usage))
                if COMMON.match(c) and bal > 0 and close:
                    if p.rdays >= RECENT_N and bal >= MIN_BAL and not p.stale:
                        q = sum(x[0] for x in p.win)
                        if q >= MIN_BAL:
                            rmp = close / (RATIO * sum(x[1] for x in p.win) / q) * 100
                            cr = crash.setdefault(ds, [0, 0, 0, 0])
                            cr[0] += 1; cr[1] += rmp < 130; cr[2] += rmp < 140; cr[3] += bal if rmp < 130 else 0
            # 官方校準：成本 × k，k＝官方融資金額 ÷ 模型融資金額合計（同市場同日），使模型總額等於官方總額
            k = loan / est_loan if full and loan and est_loan else None
            for p, close, bal, chg, usage in todo:
                q = sum(x[0] for x in p.win)
                rc = sum(x[1] for x in p.win) / q if q >= MIN_BAL else None
                cost = p.cost * (k or 1.0)
                p.hist.append((ds, close, cost, bal, chg, close / (RATIO * cost) * 100, usage,
                               p.init / bal * 100 if bal else 0,
                               close / (RATIO * p.cost_lo * (k or 1.0)) * 100 if p.cost_lo else None,
                               close / (RATIO * p.cost_hi * (k or 1.0)) * 100 if p.cost_hi else None, 1 if p.stale else 0,
                               close / (RATIO * p.cost) * 100,
                               rc, close / (RATIO * rc) * 100 if rc else None, p.rdays >= RECENT_N))
            todo.clear()
            market.append(dict(date=ds, market=mkt, maint=round(coll_stk / loan * 100, 2) if loan else None,
                               maint_all=round(coll / loan * 100, 2) if loan else None,
                               loan=loan, collateral=round(coll), balance=bal_total,
                               calib=round(est_loan / loan, 4) if full and loan and est_loan else None,
                               k=None if k is None else round(k, 4),
                               fallback=fallback, unpriced=unpriced))

    latest = days[-1]
    # 個股最新列與驗證
    rows, excluded = [], {'insufficient': 0, 'pending': 0, 'sensitive': 0, 'other': 0}
    os.makedirs(OUT_DIR, exist_ok=True)
    keep_files = set()
    for c, p in pos.items():
        if not COMMON.match(c) or not p.hist:
            continue
        h = p.hist
        fn = f'{c}.csv'
        keep_files.add(fn)
        with open(os.path.join(OUT_DIR, fn), 'w') as f:
            f.write('date,close,cost,balance,change,maint,usage,rcost,rmaint\n')
            for (ds, close, cost, bal, chg, mp, usage, *_rest) in h:  # cost、mp 為全體平均（校準後）；rcost、rmaint 為近期口徑
                rc, rmp = _rest[5], _rest[6]
                f.write(f'{ds},{close:g},{cost:.4f},{bal:g},{chg:g},{mp:.2f},{"" if usage is None else f"{usage:.2f}"},'
                        f'{"" if rc is None else f"{rc:.4f}"},{"" if rmp is None else f"{rmp:.2f}"}\n')
        last = h[-1]
        if last[0] != latest:
            continue   # 今天已無融資部位
        ds, close, cost, bal, chg, mp, usage, init_pct, mp_lo, mp_hi, stale, mp_raw, rc, rmp, rlong = last
        li = days.index(latest)
        adj = lambda d: (lambda v: v[0] * p.fac / v[1] if v[1] else None)(p.bh[d]) if d in p.bh else None
        last20 = [adj(d) for d in days[max(0, li - 19):li + 1]]
        last20 = [v for v in last20 if v is not None]
        hi20 = max(last20) if last20 else None
        rok = bool(rmp is not None and rlong and not stale and bal >= MIN_BAL)
        sens = abs((mp_lo or mp) - (mp_hi or mp))
        b5 = adj(days[li - 5]) if li >= 5 else None   # 精確 T−5，換算到今日張數基準；查無當日列＝N/A
        reason = None
        if p.days < MIN_DAYS:
            reason, key = f'有效歷史 {p.days} 日，未滿 {MIN_DAYS} 日', 'insufficient'
        elif p.bad:
            reason, key = p.bad, 'other'
        elif init_pct > MAX_INIT:
            reason, key = f'期初庫存仍占 {init_pct:.0f}%', 'pending'
        elif sens > MAX_SENS:
            reason, key = f'成本敏感度 {sens:.1f} 個百分點', 'sensitive'
        elif bal < MIN_BAL:
            reason, key = f'融資餘額 {bal:g} 張，低於 {MIN_BAL} 張', 'other'
        elif stale:
            reason, key = '當日無成交', 'other'
        if reason:
            excluded[key] += 1
        rows.append(dict(s=c, n=p.name, m=p.mkt, c=close, cost=round(cost, 2), mp=round(mp, 2),
                         u=None if usage is None else round(usage, 2), b=bal, ch=chg, raw=round(mp_raw, 2),
                         c5=None if b5 is None else round(bal - b5), d=p.days, i=round(init_pct, 1),
                         sens=round(sens, 1), ok=reason is None, why=reason,
                         rc=None if rc is None else round(rc, 2), rmp=None if rmp is None else round(rmp, 2), rok=rok,
                         dd20=round((bal / hi20 - 1) * 100, 1) if hi20 else None))
    for fn in os.listdir(OUT_DIR):
        if fn.endswith('.csv') and fn not in keep_files:
            os.remove(os.path.join(OUT_DIR, fn))

    ok = [r for r in rows if r['ok']]
    rk = [r for r in rows if r['rok']]
    rstats = dict(raw=len(rows), valid=len(rk),
                  below={str(t): sum(1 for r in rk if r['rmp'] < t) for t in (130, 140, 150)},
                  by_market={m: dict(valid=sum(1 for r in rk if r['m'] == m),
                                     below={str(t): sum(1 for r in rk if r['m'] == m and r['rmp'] < t) for t in (130, 140, 150)})
                             for m in ('TWSE', 'TPEX')})
    stats = dict(raw=len(rows), valid=len(ok), excluded=excluded,
                 below={str(t): sum(1 for r in ok if r['mp'] < t) for t in (130, 140, 150)},
                 by_market={m: dict(valid=sum(1 for r in ok if r['m'] == m),
                                    below={str(t): sum(1 for r in ok if r['m'] == m and r['mp'] < t) for t in (130, 140, 150)})
                            for m in ('TWSE', 'TPEX')})
    # 精簡輸出：只有最近 10 個交易日保留沿用價格／查無價格明細，其餘留筆數
    recent = set(days[-10:])
    for m in market:
        m['fb_n'], m['up_n'] = len(m['fallback']), len(m['unpriced'])
        for kk in ('collateral', 'balance'):
            m.pop(kk, None)
        if m['date'] not in recent:
            if not m['unpriced']:
                m.pop('unpriced')
            m.pop('fallback')
            for kk in ('calib', 'k'):
                if m.get(kk) is None:
                    m.pop(kk, None)
    # 盤中暫估用：最新交易日各普通股融資餘額（含未列入排行者），網頁以盤中價格 × 餘額 ÷ 官方融資金額暫估大盤
    balmap = {c: [p.mkt[1], p.last_bal] for c, p in pos.items() if COMMON.match(c) and p.last_bal and p.bh.get(latest)}
    out = dict(date=latest, generated=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds'),
               model=dict(version=MODEL, start=START, financing_ratio=RATIO, min_days=MIN_DAYS, max_init_pct=MAX_INIT,
                          max_sensitivity=MAX_SENS, min_balance=MIN_BAL, recent_days=RECENT_N),
               market=market, bal=balmap, basis=basis_log, stats=stats, rstats=rstats, rows=rows,
               crash=[dict(date=d, n=v[0], b130=v[1], b140=v[2], bal130=round(v[3]), taiex=taiex.get(d)) for d, v in sorted(crash.items())])
    with open(OUT_JSON, 'w') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(latest, '個股', len(rows), '有效', len(ok), '排除', excluded, '低於130', stats['below']['130'], '| 近期口徑', rstats)
    for m in market[-2:]:
        print(m['date'], m['market'], m['maint'], '校準', m['calib'], 'fallback', len(m['fallback']))


if __name__ == '__main__':
    main()
    if '--expect' in sys.argv:  # 上線後確認實際結果（防錯清單 D3）：最新資料日必須是目標日
        want = sys.argv[sys.argv.index('--expect') + 1]
        got = json.load(open(OUT_JSON))['date']
        if want and got != want:
            raise SystemExit(f'最新資料日 {got} 不是目標日 {want}')
