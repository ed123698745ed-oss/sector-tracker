"""融資觀察分頁：大盤與個股估算融資維持率，輸出 docs/margin.json 與 docs/margin/s/代號.csv。

只供觀察市場，不是交易訊號；個股為公開資料模型估算，不是券商實際整戶擔保維持率。

資料（全部為官方公開資料，原始檔存 archive/raw）
  融資：證交所 MI_MARGN（twse_margin）、櫃買 margin/balance（tpex_margin），單位張
  價格：證交所 MI_INDEX（twse）、櫃買 afterTrading/otc（tpex）的收盤價、成交股數、成交金額
  日均價＝成交金額 ÷ 成交股數；無成交日不更新價格，沿用最近一次收盤（標記為沿用）

大盤維持率（上市、上櫃分開算，不是個股平均）
  Σ（各證券融資今日餘額張數 × 1000 × 當日收盤價）÷ 該市場官方融資金額餘額
  分母：上市「信用交易統計」融資金額(仟元)今日餘額；上櫃表尾「融資金(仟元)」資餘額欄
  當日無收盤價者用最近一次收盤（fallback 清單一併輸出）

個股估算（模型 MR01，起算日 START）
  1. 逐日重播融資庫存（批次法）：每日淨融資買進為一個批次，成本＝當日均價
  2. 當日沖銷：同日融資買進與融資賣出先互抵，視為當日進出、不進庫存
  3. 出場順序（追繳優先）：當日淨賣出＋現金償還，先從估算維持率已低於 130% 的批次移出（成本高者先），
     其餘按比例自各批次移出
  4. 期初庫存：起算日已有的融資餘額為一個批次，成本設為起算日前 60 個交易日日均價的平均；同時以這 60 日的
     最低／最高日均價各算一次（成本敏感度）
  5. 統一股份基準：交易所公布的「前日餘額」與前一日「今日餘額」不同時（減資、面額分割、換發等），
     視為股數基準改變，比例 r＝前日餘額÷前一日今日餘額，各批次張數 × r、成本 ÷ r；r 不在 1/20～20 之間則判為異常
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
  - 除權息：現金股利不調整成本（與實際擔保維持率計算一致，除息後維持率下降）；配股不加計擔保品
"""
import datetime, glob, gzip, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'archive', 'raw')
OUT_JSON = os.path.join(ROOT, 'docs', 'margin.json')
OUT_DIR = os.path.join(ROOT, 'docs', 'margin', 's')
START = '20250102'   # 模型起算日（固定，起算日改變會改寫全部歷史，須經 Ed 確認）
MODEL = 'MR01'
RATIO = 0.6
MIN_DAYS, MAX_INIT, MAX_SENS, MIN_BAL = 120, 35.0, 10.0, 10
NET_DAYTRADE = True
FORCED_FIRST, CALL = True, 130.0
COMMON = re.compile(r'^[1-9]\d{3}$')


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
    """有上市、上櫃融資原始檔，且有對應收盤原始檔的日子（資料日以檔名＝已檢查過的內文日期為準）"""
    a = {os.path.basename(p)[:8] for p in glob.glob(f'{RAW}/twse_margin/*.json.gz')}
    b = {os.path.basename(p)[:8] for p in glob.glob(f'{RAW}/tpex_margin/*.json.gz')}
    return sorted(d for d in a & b if os.path.exists(f'{RAW}/twse/{d}.json.gz') and os.path.exists(f'{RAW}/tpex/{d}.json.gz'))


def price_days_before(ds, n):
    """ds 之前 n 個有上市收盤原始檔的日子（期初成本用）"""
    ds_all = sorted(os.path.basename(p)[:8] for p in glob.glob(f'{RAW}/twse/*.json.gz'))
    prev = [d for d in ds_all if d < ds]
    return prev[-n:]


class Pos:
    __slots__ = ('mkt', 'name', 'inv', 'cost', 'cost_lo', 'cost_hi', 'init', 'days', 'bad', 'last_bal', 'hist',
                 'last_close', 'stale', 'lots')

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
        self.lots = []   # 批次 [張數, 成本, 期初低成本, 期初高成本, 是否期初]


def main():
    days = [d for d in trading_days() if d >= START]
    if not days:
        raise SystemExit('沒有融資原始檔')
    # 期初成本：起算日前 60 個交易日的日均價
    pre = price_days_before(days[0], 60)
    pre_avg = {}
    for d in pre:
        for src, fn in (('twse', prices_twse), ('tpex', prices_tpex)):
            for c, (_, _, a) in fn(load(src, d)).items():
                pre_avg.setdefault(c, []).append(a)

    pos = {}
    market = []
    last_px = {}   # 代號 → (日期, 收盤)
    for di, ds in enumerate(days):
        px = {}
        for src, fn in (('twse', prices_twse), ('tpex', prices_tpex)):
            for c, v in fn(load(src, ds)).items():
                px[c] = v
                last_px[c] = (ds, v[1])
        for mkt, src, parse in (('TWSE', 'twse_margin', margin_twse), ('TPEX', 'tpex_margin', margin_tpex)):
            loan, rows = parse(load(src, ds))
            coll = est_loan = 0.0
            bal_total = 0.0
            fallback = []
            todo = []
            for c, r in rows.items():
                p = pos.get(c)
                if p is None:
                    p = pos[c] = Pos(mkt, r['name'])
                p.name = r['name']
                bal = r['bal']
                # 股數基準：交易所前日餘額與我們記錄的前一日餘額不同（減資、面額分割等）
                if p.last_bal is not None and p.lots and abs(r['prev'] - p.last_bal) > 0.5:
                    if p.last_bal > 0 and r['prev'] > 0:
                        k = r['prev'] / p.last_bal
                        if 1 / 20 <= k <= 20:
                            for L in p.lots:
                                L[0] *= k; L[1] /= k; L[2] /= k; L[3] /= k
                        else:
                            p.bad = f'{ds} 股數基準比例異常 {k:.3f}'
                    else:
                        p.bad = f'{ds} 前日餘額不連續'
                name_px = px.get(c)
                avg = name_px[2] if name_px else None
                close = name_px[1] if name_px else (last_px.get(c) or (None, None))[1]
                if not name_px and bal > 0:
                    if close is not None:
                        fallback.append(dict(symbol=c, balance=bal, close=close, price_date=last_px[c][0]))
                p.stale = name_px is None
                if not p.lots and r['prev'] > 0 and p.last_bal is None:
                    # 期初庫存：起算日已有的餘額，或起算後才第一次出現就已有前日餘額（轉上市等），成本未知
                    hist = pre_avg.get(c) if di == 0 else None
                    if hist:
                        base, lo, hi = sum(hist) / len(hist), min(hist), max(hist)
                    else:
                        base = lo = hi = avg or close
                    if base:
                        p.lots = [[r['prev'], base, lo, hi, 1]]
                # 當日沖銷：同日融資買進與融資賣出先互抵（視為當日進出，不進庫存），只有淨買進才以當日均價入庫
                net = min(r['buy'], r['sell']) if NET_DAYTRADE else 0
                buy, out = r['buy'] - net, r['sell'] - net + r['repay']
                if buy > 0 and (avg or close):
                    q = avg or close
                    p.lots.append([buy, q, q, q, 0])
                if out > 0 and p.lots:
                    # 追繳優先：估算維持率已低於 130% 的批次先出場（成本高者先），其餘按比例移出
                    if close and FORCED_FIRST:
                        for L in sorted((L for L in p.lots if close / (RATIO * L[1]) * 100 < CALL), key=lambda L: -L[1]):
                            x = min(L[0], out); L[0] -= x; out -= x
                            if out <= 0:
                                break
                    tot = sum(L[0] for L in p.lots)
                    if out > 0 and tot > 0:
                        keep = max(tot - out, 0) / tot
                        for L in p.lots:
                            L[0] *= keep
                    p.lots = [L for L in p.lots if L[0] > 1e-9]
                # 與交易所今日餘額對齊（正常情況恆等式成立，差異只來自上面的未知成本或四捨五入）
                tot = sum(L[0] for L in p.lots)
                if bal <= 0:
                    p.lots = []
                elif tot > 0 and abs(tot - bal) > 1e-6:
                    for L in p.lots:
                        L[0] *= bal / tot
                if len(p.lots) > 400:   # 合併同成本附近的舊批次，控制記憶體
                    p.lots.sort(key=lambda L: L[1])
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
                # 大盤
                if bal > 0 and close is not None:
                    coll += bal * 1000 * close
                bal_total += bal
                if bal > 0 and p.cost:
                    est_loan += bal * 1000 * p.cost * RATIO
                # 個股歷史（只記普通股、有部位的日子）；校準係數待全市場加總後套用
                if COMMON.match(c) and bal > 0 and p.cost and close:
                    usage = bal / r['limit'] * 100 if r['limit'] else None
                    todo.append((p, close, bal, bal - r['prev'], usage))
            # 官方校準：成本 × k，k＝官方融資金額 ÷ 模型融資金額合計（同市場同日），使模型總額等於官方總額
            k = loan / est_loan if loan and est_loan else 1.0
            for p, close, bal, chg, usage in todo:
                cost = p.cost * k
                p.hist.append((ds, close, cost, bal, chg, close / (RATIO * cost) * 100, usage,
                               p.init / bal * 100 if bal else 0,
                               close / (RATIO * p.cost_lo * k) * 100 if p.cost_lo else None,
                               close / (RATIO * p.cost_hi * k) * 100 if p.cost_hi else None, 1 if p.stale else 0,
                               close / (RATIO * p.cost) * 100))
            todo.clear()
            market.append(dict(date=ds, market=mkt, maint=round(coll / loan * 100, 4) if loan else None,
                               loan=loan, collateral=round(coll), balance=bal_total,
                               calib=round(est_loan / loan, 4) if loan else None, k=round(k, 4),
                               fallback=fallback))

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
            f.write('date,close,cost,balance,change,maint,usage\n')
            for (ds, close, cost, bal, chg, mp, usage, *_rest) in h:  # cost、mp 為校準後
                f.write(f'{ds},{close:g},{cost:.4f},{bal:g},{chg:g},{mp:.2f},{"" if usage is None else f"{usage:.2f}"}\n')
        last = h[-1]
        if last[0] != latest:
            continue   # 今天已無融資部位
        ds, close, cost, bal, chg, mp, usage, init_pct, mp_lo, mp_hi, stale, mp_raw = last
        sens = abs((mp_lo or mp) - (mp_hi or mp))
        b5 = next((x[3] for x in reversed(h[:-1]) if days.index(x[0]) <= days.index(latest) - 5), None) \
            if len(h) > 1 else None
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
                         c5=None if b5 is None else bal - b5, d=p.days, i=round(init_pct, 1),
                         sens=round(sens, 1), ok=reason is None, why=reason))
    for fn in os.listdir(OUT_DIR):
        if fn.endswith('.csv') and fn not in keep_files:
            os.remove(os.path.join(OUT_DIR, fn))

    ok = [r for r in rows if r['ok']]
    stats = dict(raw=len(rows), valid=len(ok), excluded=excluded,
                 below={str(t): sum(1 for r in ok if r['mp'] < t) for t in (130, 140, 150)},
                 by_market={m: dict(valid=sum(1 for r in ok if r['m'] == m),
                                    below={str(t): sum(1 for r in ok if r['m'] == m and r['mp'] < t) for t in (130, 140, 150)})
                            for m in ('TWSE', 'TPEX')})
    out = dict(date=latest, generated=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds'),
               model=dict(version=MODEL, start=START, financing_ratio=RATIO, min_days=MIN_DAYS, max_init_pct=MAX_INIT,
                          max_sensitivity=MAX_SENS, min_balance=MIN_BAL),
               market=market, stats=stats, rows=rows)
    with open(OUT_JSON, 'w') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(latest, '個股', len(rows), '有效', len(ok), '排除', excluded, '低於130', stats['below']['130'])
    for m in market[-2:]:
        print(m['date'], m['market'], m['maint'], '校準', m['calib'], 'fallback', len(m['fallback']))


if __name__ == '__main__':
    main()
    if '--expect' in sys.argv:  # 上線後確認實際結果（防錯清單 D3）：最新資料日必須是目標日
        want = sys.argv[sys.argv.index('--expect') + 1]
        got = json.load(open(OUT_JSON))['date']
        if want and got != want:
            raise SystemExit(f'最新資料日 {got} 不是目標日 {want}')
