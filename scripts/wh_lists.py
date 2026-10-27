"""權值與高價股觀察分頁：建立每月觀察名單。

規則（Ed 2026-10-27 確認）：每月最後一個交易日收盤排名，次月使用。
  hp   高價股前 30：上市櫃普通股未還原收盤價
  otc  上櫃權值前 30：收盤價 × 櫃買公布發行股數
  twse 上市權值前 50：收盤價 × 普通股股數（財報股本推算，見 twse_shares.py；尚未完成時略過）
月底無成交者以該月最後一筆收盤計；當月完全無成交不納入。
上市股數另做事件調整：財報季底之後到排名日之間，若有證交所公告的減資恢復買賣、變更面額恢復買賣或除權（配股），
股數乘上「停止買賣前收盤÷恢復買賣參考價」，避免事件後到下季財報前股數過時。
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
            if kind == 'TWT49U':
                if r[6].strip() == '息': continue
                if r[6].strip() != '權':
                    if prev / ref > 1.2: unsplit.append((ds, c, round(prev / ref, 3)))
                    continue
            events.setdefault(c, []).append((ds, prev / ref))
    qend = {1: '0331', 2: '0630', 3: '0930', 4: '1231'}
    adj_log = {}

    # 每月最後交易日索引
    ends = {}
    for i, ds in enumerate(dates):
        ends[ds[:6]] = i
    starts = {}
    for i, ds in enumerate(dates):
        starts.setdefault(ds[:6], i)

    out = {}
    for ym, ie in sorted(ends.items()):
        i0 = starts[ym]
        last = {}
        for c, arr in px.items():
            for i in range(ie, i0 - 1, -1):
                if arr[i]:
                    last[c] = (arr[i], i); break
        hp = sorted(((c, v[0]) for c, v in last.items()), key=lambda x: -x[1])[:30]
        otc = []
        for c, (p, i) in last.items():
            s = osh.get(c)
            if s and s[ie]:  # 排名日當天仍在上櫃掛牌
                otc.append((c, round(p * s[ie] / 1e8, 1)))
        otc = sorted(otc, key=lambda x: -x[1])[:30]
        rec = {'asof': dates[ie], 'hp': hp, 'otc': otc}
        if tw and ym in tw:
            ry, qq = avail_quarter(ym)
            qd = '%d%s' % (ry + 1911, qend[qq])
            cap = []
            for c, n in tw[ym].items():
                if c not in last or (c in osh and osh[c][ie]): continue
                fx = 1.0
                for ds_, r in events.get(c, []):
                    if qd < ds_ <= dates[ie]: fx *= r
                if fx != 1.0: adj_log.setdefault(c, []).append((ym, round(fx, 3)))
                cap.append((c, round(last[c][0] * n * fx / 1e8, 1)))
            rec['twse'] = sorted(cap, key=lambda x: -x[1])[:50]
        out[ym] = rec
    json.dump(out, open(os.path.join(ROOT, 'config', 'wh_lists.json'), 'w'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    json.dump({'events': events, 'adj': adj_log, 'unsplit': unsplit}, open(os.path.join(ROOT, 'cache', 'wh_share_events.json'), 'w'), ensure_ascii=False)
    print('months', len(out), 'with twse', sum('twse' in v for v in out.values()))


if __name__ == '__main__':
    main()
