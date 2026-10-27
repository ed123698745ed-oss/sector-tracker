"""權值與高價股觀察分頁：建立每月觀察名單。

規則（Ed 2026-10-27 確認）：每月最後一個交易日收盤排名，次月使用。
  hp   高價股前 30：上市櫃普通股未還原收盤價
  otc  上櫃權值前 30：收盤價 × 櫃買公布發行股數
  twse 上市權值前 50：收盤價 × 普通股股數（財報股本推算，見 twse_shares.py；尚未完成時略過）
排名日當天須有成交（有收盤價）才納入；無成交、停牌、已終止上市櫃者不列入，由下一名遞補（Ed 2026-10-27）。
同分時市值大者排前（高價股同價比市值；市值同分比收盤價）（Ed 2026-10-27）。
上市股數另做事件調整：財報季底之後到排名日之間，若有證交所公告的減資恢復買賣、變更面額恢復買賣或除權（配股），
股數乘上新股數÷舊股數：面額變更、彌補虧損減資、配股＝停止買賣前收盤÷恢復買賣參考價；
退還股款（現金減資）每股退還面額，減資比率 k＝(前收盤−參考價)÷(面額−參考價)，比值＝1−k；
若該季財報股數相對前一季的變化已約等於事件比值（例：面額變更基準日在季底前、恢復買賣在季底後），不重複調整。
輸出：config/wh_lists.json  {"YYYYMM"(排名月): {"asof": 排名日, "hp": [[代號, 數值], ...], "otc": [...], "twse": [...]}}
"""
import gzip, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from twse_shares import avail_quarter  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    d = json.load(gzip.open(os.path.join(ROOT, 'cache', 'wh_px.json.gz'), 'rt', encoding='utf-8'))
    dates, px, osh = d['dates'], d['px'], d['otc_sh']
    tw_path = os.path.join(ROOT, 'cache', 'wh_twse_shares.json')
    tw = json.load(open(tw_path)) if os.path.exists(tw_path) else None  # {YYYYMM: {代號: 股數}}

    # 股數事件（只用證交所官方公告）：減資恢復買賣 TWTAUU、變更面額恢復買賣 TWTB8U、除權（配股）TWT49U「權」。
    # 比值＝停止買賣前（除權前）收盤÷恢復買賣（除權）參考價＝新股數÷舊股數。
    # 「權息」同時配股配息無法拆開，不調整，只記錄比值>1.2 者供檢查。
    import glob, re as _re
    events, unsplit = {}, []
    note_path = os.path.join(ROOT, 'cache', 'wh_twse_shares_note.json')
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

    def roc(s):
        m = _re.match(r'(\d+)\D+(\d+)\D+(\d+)', s)
        return '%d%02d%02d' % (int(m[1]) + 1911, int(m[2]), int(m[3]))

    def f(x):
        try: return float(str(x).replace(',', ''))
        except ValueError: return None
    for fp in sorted(glob.glob(os.path.join(edir, '*.json'))):
        kind = os.path.basename(fp)[:6]
        for r in json.load(open(fp)).get('data') or []:
            prev, ref = f(r[3]), f(r[4])
            if not prev or not ref: continue
            ds, c = roc(r[0]), r[1].strip()
            if kind == 'TWTAUU' and '退還' in (r[9] or ''):
                par = par_of(c, ds)
                if abs(par - ref) > 0.01:
                    k = (prev - ref) / (par - ref)
                    if 0 < k < 1:
                        events.setdefault(c, []).append((ds, 1 - k)); continue
                unsplit.append((ds, c, 'cash_reduction_unsolved'))
                continue
            if kind == 'TWT49U':
                if r[6].strip() == '息': continue
                if r[6].strip() != '權':
                    if prev / ref > 1.2: unsplit.append((ds, c, round(prev / ref, 3)))
                    continue
            events.setdefault(c, []).append((ds, prev / ref))
    qend = {1: '0331', 2: '0630', 3: '0930', 4: '1231'}
    byq_path = os.path.join(ROOT, 'cache', 'wh_twse_byq.json')
    byq = json.load(open(byq_path)) if os.path.exists(byq_path) else {}
    adj_log = {}

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
        if tw and ym in tw:
            ry, qq = avail_quarter(ym)
            qd = '%d%s' % (ry + 1911, qend[qq])
            pq = (ry, qq - 1) if qq > 1 else (ry - 1, 4)
            for c, n in tw[ym].items():
                if c not in last or c in otc_cap: continue
                fx = 1.0
                s_now, s_prev = byq.get('%03d%02d' % (ry, qq), {}).get(c), byq.get('%03d%02d' % pq, {}).get(c)
                for ds_, r in events.get(c, []):
                    if not (qd < ds_ <= dates[ie]): continue
                    # 事件生效早於季底、季報股數已反映（季報股數較前季的變化≈事件比值）時不重複調整
                    if s_now and s_prev and abs((s_now / s_prev) / r - 1) < 0.15: continue
                    fx *= r
                if fx != 1.0: adj_log.setdefault(c, []).append((ym, round(fx, 3)))
                tw_cap[c] = round(last[c] * n * fx / 1e8, 1)
            rec['twse'] = sorted(tw_cap.items(), key=lambda x: (-x[1], -last[x[0]], x[0]))[:50]
        cap_any = {**tw_cap, **otc_cap}
        rec['otc'] = sorted(otc_cap.items(), key=lambda x: (-x[1], -last[x[0]], x[0]))[:30]
        rec['hp'] = sorted(((c, p) for c, p in last.items()), key=lambda x: (-x[1], -cap_any.get(x[0], 0), x[0]))[:30]
        out[ym] = rec
    json.dump(out, open(os.path.join(ROOT, 'config', 'wh_lists.json'), 'w'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    json.dump({'events': events, 'adj': adj_log, 'unsplit': unsplit}, open(os.path.join(ROOT, 'cache', 'wh_share_events.json'), 'w'), ensure_ascii=False)
    print('months', len(out), 'with twse', sum('twse' in v for v in out.values()))


if __name__ == '__main__':
    main()
