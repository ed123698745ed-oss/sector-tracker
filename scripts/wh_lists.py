"""權值與高價股觀察分頁：建立每月觀察名單。

規則（Ed 2026-10-27 確認）：每月最後一個交易日收盤排名，次月使用。
  hp   高價股前 30：上市櫃普通股未還原收盤價
  otc  上櫃權值前 30：收盤價 × 櫃買公布發行股數
  twse 上市權值前 50：收盤價 × 普通股股數（財報股本推算，見 twse_shares.py；尚未完成時略過）
月底無成交者以該月最後一筆收盤計；當月完全無成交不納入。
輸出：config/wh_lists.json  {"YYYYMM"(排名月): {"asof": 排名日, "hp": [[代號, 數值], ...], "otc": [...], "twse": [...]}}
"""
import gzip, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    d = json.load(gzip.open(os.path.join(ROOT, 'cache', 'wh_px.json.gz'), 'rt', encoding='utf-8'))
    dates, px, osh = d['dates'], d['px'], d['otc_sh']
    tw_path = os.path.join(ROOT, 'cache', 'wh_twse_shares.json')
    tw = json.load(open(tw_path)) if os.path.exists(tw_path) else None  # {YYYYMM: {代號: 股數}}

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
            cap = [(c, round(last[c][0] * n / 1e8, 1)) for c, n in tw[ym].items() if c in last and (c not in osh or not osh[c][ie])]
            rec['twse'] = sorted(cap, key=lambda x: -x[1])[:50]
        out[ym] = rec
    json.dump(out, open(os.path.join(ROOT, 'config', 'wh_lists.json'), 'w'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    print('months', len(out), 'with twse', sum('twse' in v for v in out.values()))


if __name__ == '__main__':
    main()
