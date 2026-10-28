"""權值與高價股觀察分頁：建立每月觀察名單。

規則（Ed 2026-10-27 確認）：每月最後一個交易日收盤排名，次月使用。
  hp   高價股前 30：上市櫃普通股未還原收盤價
  otc  上櫃權值前 30：收盤價 × 櫃買公布發行股數
  twse 上市權值前 50：收盤價 × 普通股股數。R06 起股數＝證交所 MI_QFIIS 排名日「發行股數」（含之後已下市公司），
       近 120 日內的分割／配股／減資事件若尚未反映於發行股數，以事件倍率補上；財報推算法（twse_shares.py，
       WH_SHARES=mops）僅作交叉核對（Ed 2026-10-28；原因：財報彙總表查不到已下市公司，且推算有多筆錯誤）
排名日當天須有成交（有收盤價）才納入；無成交、停牌、已終止上市櫃者不列入，由下一名遞補（Ed 2026-10-27）。
同分時市值大者排前（高價股同價比市值；市值同分比收盤價）（Ed 2026-10-27）。
上市股數另做事件調整：財報季底之後到排名日之間，若有證交所公告的減資恢復買賣、變更面額恢復買賣或除權（配股），
股數乘上新股數÷舊股數：面額變更、彌補虧損減資、配股＝停止買賣前收盤÷恢復買賣參考價；
退還股款（現金減資）每股退還面額，減資比率 k＝(前收盤−參考價)÷(面額−參考價)，比值＝1−k；
權息：比值＝1＋配股率；配股率依序取「除權息基準日公告」(mops_div_notice.py)、手動補登(config/div_overrides.json)、
「股利分派情形」(mops_div.py)，面額用事件當時財報推得者，三者皆須通過參考價驗證（誤差<1%）；皆無者不調整並列入
audit/wh_skipped_events_*.csv（Eve 2026-10-28 R04 複審：富邦媒 2021/7/5 配股 3 元曾被漏調）。
是否已反映於季報：季報股數較前季的變動幅度達事件幅度 80%～125% 才視為已反映（減資／變更面額另須停止買賣始於季底前）；
現金增資除權（減除股利參考價≠除權息參考價）不調整股數，新股待下一季財報反映（Ed 2026-10-27）；
否則一律調整（Eve 2026-10-27 複審：原 15% 容差會漏調小額配股，例：合庫金 2021/9 配股約 2%）。
輸出：config/wh_lists.json  {"YYYYMM"(排名月): {"asof": 排名日, "hp": [[代號, 數值], ...], "otc": [...], "twse": [...]}}
"""
import gzip, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from twse_shares import avail_quarter  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    d = json.load(gzip.open(os.path.join(ROOT, 'cache', 'wh_px.json.gz'), 'rt', encoding='utf-8'))
    dates, px, osh = d['dates'], d['px'], d['otc_sh']
    tw_path = os.path.join(ROOT, 'cache', 'wh_twse_shares.json')
    tw = json.load(open(tw_path)) if os.path.exists(tw_path) else None  # {YYYYMM: {代號: 股數}}

    # 股數事件（證交所官方公告）：減資恢復買賣 TWTAUU、變更面額恢復買賣 TWTB8U、除權 TWT49U「權」「權息」。
    # 比值＝新股數÷舊股數：「權」、面額變更、彌補虧損減資＝前收盤÷參考價；退還股款見下；
    # 「權息」以股東會決議配股率（公開資訊觀測站 t05st09）計算，並以參考價驗證。
    import glob, re as _re
    events, unsplit = {}, []
    note_path = os.path.join(ROOT, 'cache', 'wh_twse_shares_note.json')
    if not os.path.exists(note_path):  # GitHub Actions 無 cache：用已提交的面額表（同一份內容）
        note_path = os.path.join(ROOT, 'config', 'wh_par_note.json')
    pnt = json.load(open(note_path)).get('par_not_10', {}) if os.path.exists(note_path) else {}

    def par_of(c, ds):
        """事件日前最近一季推得的面額；查無即 10 元"""
        y = int(ds[:4]) - 1911; q = (int(ds[4:6]) - 1) // 3 + 1
        best = 10
        for k, v in sorted(pnt.get(c, {}).items()):
            ky, kq = int(k.split()[0]), int(k.split()[1][1:])
            if (ky, kq) < (y, q): best = v
        return best
    edir = os.path.join(ROOT, 'archive', 'raw', 'twse_events')
    from mops_div import parse_div
    div_cache = {}
    from mops_div_notice import parse_notice
    notices = {}
    for fp in glob.glob(os.path.join(ROOT, 'archive', 'raw', 'mops_div_notice', '*_*_*.html.gz')):
        if fp.endswith('_list.html.gz'): continue
        notices.setdefault(os.path.basename(fp)[:4], []).append(parse_notice(fp))
    ovp = os.path.join(ROOT, 'config', 'div_overrides.json')
    div_override = json.load(open(ovp)) if os.path.exists(ovp) else {}

    def stock_rate(c, ds, prev, ref):
        """權息事件的配股率 s（新股數＝舊股數×(1+s)）：取該年度股東會決議的配股（元/股）÷面額，
        並以「(前收盤−現金股利)÷(1+s)≈參考價」驗證（誤差<1%）；查無資料或驗證不過回傳 None"""
        # 優先：除權息基準日公告（交易日相符者）→ 手動補登 → 股利分派情形；皆須通過參考價驗證
        cands = [n for n in notices.get(c, []) if n['exdate'] == ds]
        ov = div_override.get(c, {}).get(ds)
        if ov: cands.append(ov)
        for n in cands:
            s = n['stock'] / par_of(c, ds)
            if abs((prev - n['cash']) / (1 + s) / ref - 1) < 0.01:
                return s
        y = int(ds[:4]) - 1911
        for yy in (y, y - 1):
            k = (c, yy)
            if k not in div_cache:
                fp = os.path.join(ROOT, 'archive', 'raw', 'mops_div', '%s_%d.html.gz' % k)
                div_cache[k] = parse_div(fp) if os.path.exists(fp) else None
            for cash, stock, _par_page in div_cache[k] or []:
                # 觀測站頁面的面額是「目前」面額（例：國巨 2025 年面額變更為 2.5 元後，舊年度頁面也顯示 2.5），
                # 改用事件當時由財報推得的面額
                s = stock / par_of(c, ds)
                if abs((prev - cash) / (1 + s) / ref - 1) < 0.01:
                    return s
        return None

    def roc(s):
        m = _re.match(r'(\d+)\D+(\d+)\D+(\d+)', s)
        return '%d%02d%02d' % (int(m[1]) + 1911, int(m[2]), int(m[3]))

    def f(x):
        try: return float(str(x).replace(',', ''))
        except ValueError: return None
    for fp in sorted(glob.glob(os.path.join(edir, '*.json'))):
        kind = os.path.basename(fp)[:6]
        jf = json.load(open(fp)); flds = [x.strip() for x in jf.get('fields') or []]
        i_why = flds.index('減資原因') if '減資原因' in flds else None
        # 權值、息值分列（2010 年以前格式）：配股率可直接由 (前收盤−息值)÷參考價−1 求得，不需觀測站股利資料。
        # 限 2015 年以前，2015 起沿用凍結名單（R06）的算法
        old49 = kind == 'TWT49U' and '息值' in flds and '權值' in flds and os.path.basename(fp)[7:11] < '2015'
        for r in jf.get('data') or []:
            prev, ref = f(r[3]), f(r[4])
            if not prev or not ref: continue
            ds, c = roc(r[0]), r[1].strip()
            if old49:
                wv, xv = f(r[flds.index('權值')]) or 0, f(r[flds.index('息值')]) or 0
                if wv <= 0: continue  # 純除息
                s = (prev - xv) / ref - 1  # 參考價＝(前收盤−息值)÷(1＋配股率)
                if s > 1e-6: events.setdefault(c, []).append((ds, 1 + s, 'ex'))
                continue
            if kind == 'TWTAUU' and i_why is None:
                unsplit.append((ds, c, 'reduction_reason_unknown'))  # 2011 年格式無減資原因欄
            if kind == 'TWTAUU' and i_why is not None and '退還' in (r[i_why] or ''):
                par = par_of(c, ds)
                if abs(par - ref) > 0.01:
                    k = (prev - ref) / (par - ref)
                    if 0 < k < 1:
                        events.setdefault(c, []).append((ds, 1 - k, 'halt')); continue
                unsplit.append((ds, c, 'cash_reduction_unsolved'))
                continue
            if kind == 'TWT49U':
                typ = r[flds.index('權/息')].strip()
                if typ == '息': continue
                # 減除股利參考價＝只扣股利（現金＋股票）後的參考價；與除權息參考價不同時代表含現金增資除權（證交所附註）
                dref = (f(r[flds.index('減除股利參考價')]) if '減除股利參考價' in flds else None) or ref
                if abs(dref - ref) > 0.005:
                    unsplit.append((ds, c, 'cash_capital_increase'))  # 依 Ed 決定不調整，待下一季財報反映
                if typ == '權':
                    s = prev / dref - 1
                else:
                    s = stock_rate(c, ds, prev, dref)
                    if s is None:
                        unsplit.append((ds, c, 'stock_rate_missing'))
                        # 敏感度測試用：WH_UNRESOLVED=max 時以上限（假設無現金股利）調整；正式名單不調整
                        if os.environ.get('WH_UNRESOLVED') != 'max': continue
                        s = prev / dref - 1
                if s > 1e-6:
                    events.setdefault(c, []).append((ds, 1 + s, 'ex'))
                continue
            events.setdefault(c, []).append((ds, prev / ref, 'halt'))
    qend = {1: '0331', 2: '0630', 3: '0930', 4: '1231'}
    byq_path = os.path.join(ROOT, 'cache', 'wh_twse_byq.json')
    byq = json.load(open(byq_path)) if os.path.exists(byq_path) else {}
    adj_log = {}
    detail = {}  # 稽核用：各月上市前 60 的收盤、季報股數、事件倍率
    rank80 = set()  # 曾進上市市值前 80 者：配股率資料的抓取範圍（含邊界緩衝）

    didx = {ds: i for i, ds in enumerate(dates)}
    # 股數來源：WH_SHARES=qfiis 用證交所 MI_QFIIS 發行股數（R06 起），否則沿用財報推算（R05 以前）
    SRC = os.environ.get('WH_SHARES', 'qfiis')  # Ed 2026-10-28 採 R06：預設證交所發行股數
    qf = {}
    if SRC == 'qfiis':
        qdir = os.path.join(ROOT, 'archive', 'raw', 'twse_qfiis')
        for fn in os.listdir(qdir):
            j = json.load(gzip.open(os.path.join(qdir, fn)))
            qf[fn[:8]] = {r[0].strip(): int(r[3].replace(',', '')) for r in j['data']
                          if re.fullmatch(r'[1-9]\d{3}', r[0].strip()) and not r[0].startswith('91')}
    qf_dates = sorted(qf)

    def shift_days(ds, k):
        import datetime as _dt
        return (_dt.date(int(ds[:4]), int(ds[4:6]), int(ds[6:])) + _dt.timedelta(days=k)).strftime('%Y%m%d')

    def halt_start(c, ds):
        """恢復買賣日之前最後一個有成交的交易日（停止買賣始日前一日）"""
        arr = px.get(c) or []
        i = didx.get(ds)
        if i is None:
            i = next((j for j, d0 in enumerate(dates) if d0 >= ds), len(dates))
        for j in range(i - 1, -1, -1):
            if arr and arr[j]: return dates[j]
        return '00000000'

    # 每月最後交易日索引
    ends = {}
    for i, ds in enumerate(dates):
        ends[ds[:6]] = i
    starts = {}
    for i, ds in enumerate(dates):
        starts.setdefault(ds[:6], i)

    # 最新一個月尚未結束（資料最後一天所在月份），不排名
    ends.pop(dates[-1][:6], None)
    out = {}
    for ym, ie in sorted(ends.items()):
        last = {c: arr[ie] for c, arr in px.items() if arr[ie]}  # 排名日當天有成交
        otc_cap = {c: round(p * osh[c][ie] / 1e8, 1) for c, p in last.items() if c in osh and osh[c][ie]}
        rec = {'asof': dates[ie]}
        tw_cap = {}
        detail_m = {}
        if SRC == 'qfiis' and dates[ie] in qf:
            # 股數＝證交所 MI_QFIIS 排名日「發行股數」；近 120 日內的股數事件若尚未反映於發行股數
            # （與事件前一個月底的發行股數相比，變動幅度未達事件幅度 80%～125%），以事件倍率補上
            qn = qf[dates[ie]]
            for c, n in qn.items():
                if c not in last or c in otc_cap or c not in px: continue
                fx = 1.0; evs = []
                for ds_, r, kd in events.get(c, []):
                    if not (shift_days(dates[ie], -120) < ds_ <= dates[ie]): continue
                    pm = max((m for m in qf_dates if m < ds_), default=None)
                    s_pm = qf[pm].get(c) if pm else None
                    if s_pm and abs(math.log(r)) > 1e-6 and 0.8 <= math.log(n / s_pm) / math.log(r) <= 1.25:
                        continue
                    fx *= r; evs.append([ds_, round(r, 9), kd])
                if fx != 1.0: adj_log.setdefault(c, []).append((ym, round(fx, 3)))
                tw_cap[c] = round(last[c] * n * fx / 1e8, 1)
                detail_m[c] = {'close': last[c], 'q_shares': n, 'quarter': 'QFIIS' + dates[ie], 'factor': round(fx, 9), 'events': evs}
        elif tw and ym in tw:
            ry, qq = avail_quarter(ym)
            qd = '%d%s' % (ry + 1911, qend[qq])
            pq = (ry, qq - 1) if qq > 1 else (ry - 1, 4)
            for c, n in tw[ym].items():
                if c not in last or c in otc_cap: continue
                fx = 1.0
                s_now, s_prev = byq.get('%03d%02d' % (ry, qq), {}).get(c), byq.get('%03d%02d' % pq, {}).get(c)
                for ds_, r, kd in events.get(c, []):
                    if not (qd < ds_ <= dates[ie]): continue
                    # 是否已反映於季報：季報股數相對前一季的變動幅度（對數）須達事件變動幅度的 80%～125%
                    # 才視為已反映（Eve 2026-10-27 複審：原「比值相差 15%」會把股數未變的小額配股誤判為已反映，
                    # 例：合庫金 2021/9 配股約 2%）。除權事件部分公司會把股東會已通過的待分配股票股利列入季報
                    # 「股本」（例：緯穎 2026Q2），故以股數變動判定；減資／變更面額另須停止買賣始於季底以前。
                    if s_now and s_prev and abs(math.log(r)) > 1e-6:
                        share = math.log(s_now / s_prev) / math.log(r)
                        if 0.8 <= share <= 1.25 and (kd == 'ex' or halt_start(c, ds_) <= qd):
                            continue
                    fx *= r
                if fx != 1.0: adj_log.setdefault(c, []).append((ym, round(fx, 3)))
                tw_cap[c] = round(last[c] * n * fx / 1e8, 1)
                detail_m[c] = {'close': last[c], 'q_shares': n, 'quarter': '%03d%02d' % (ry, qq), 'factor': round(fx, 9),
                               'events': [[ds_, round(r, 9), kd] for ds_, r, kd in events.get(c, []) if qd < ds_ <= dates[ie]]}
        if tw_cap:
            rk = sorted(tw_cap.items(), key=lambda x: (-x[1], -last[x[0]], x[0]))
            rec['twse'] = rk[:50]
            detail[ym] = {c: dict(detail_m[c], cap=v, rank=i + 1) for i, (c, v) in enumerate(rk[:60])}
            for c, _ in rk[:80]: rank80.add(c)
        cap_any = {**tw_cap, **otc_cap}
        rec['otc'] = sorted(otc_cap.items(), key=lambda x: (-x[1], -last[x[0]], x[0]))[:30]
        rec['hp'] = sorted(((c, p) for c, p in last.items()), key=lambda x: (-x[1], -cap_any.get(x[0], 0), x[0]))[:30]
        out[ym] = rec
    json.dump(detail, open(os.path.join(ROOT, 'cache', 'wh_twse_detail%s.json' % ('_max' if os.environ.get('WH_UNRESOLVED') == 'max' else '')), 'w'), separators=(',', ':'))
    json.dump(out, open(os.path.join(ROOT, 'config', 'wh_lists.json'), 'w'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    json.dump({'events': events, 'adj': adj_log, 'unsplit': unsplit}, open(os.path.join(ROOT, 'cache', 'wh_share_events.json'), 'w'), ensure_ascii=False)
    json.dump(sorted(rank80), open(os.path.join(ROOT, 'cache', 'wh_rank80.json'), 'w'))
    print('months', len(out), 'with twse', sum('twse' in v for v in out.values()))


if __name__ == '__main__':
    main()
