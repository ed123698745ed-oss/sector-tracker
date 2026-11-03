"""可轉債追蹤分頁：由 archive/raw/tpex_cb 全部原始檔計算每日分布，輸出 docs/cb.json、docs/cb_list.json。

只供觀察市場，不是交易訊號。口徑依《Elon交接_2026-11-03_可轉債追蹤分頁_給Emit》，規則版本 CB01：
  母體：當日檔案內所有代號（含交換公司債），只取「等價」列，排除議價
  價格：主口徑＝明日參價（當日有等價成交＝收市；無成交沿用前一參考價），只取 >0
  對照口徑：traded＝只算當日有等價成交者、以收市計；age60＝剔除掛牌未滿 60 個交易日的新債
    （掛牌日數以資料內首見日起算；2007-01-02 已存在者無法得知，視為已滿 60 日）
  每日指標：檔數、＜100 占比、≤105 占比、≤110 占比、中位數
  百分位：該值在 2007-01-02 至當日（含）全部交易日中的位置＝(≤ 該值的天數) ÷ 總天數
    中位數越低越極端，網頁另以 100−百分位 呈現「低於多少比例的歷史日」
  近 20 日變化：≤105 占比 當日 − 20 個交易日前，同法算百分位
  歷史極端（暫用 Elon 參考值，待 Ed 確認）：≤105 占比 ≥70%；期間合併相隔 ≤20 個交易日的段落

用法：python3 scripts/cb_build.py [--expect YYYYMMDD]
"""
import datetime as dt, json, os, sys
from bisect import bisect_right
from cb_common import ROOT, archived_dates, closed_dates, load

RULE = 'CB01'
EXTREME = 0.70        # ≤105 占比門檻（暫用）
MERGE_GAP = 20
AGE_MIN = 60
TPE = dt.timezone(dt.timedelta(hours=8))


def stats(prices):
    n = len(prices)
    if n == 0:
        return [0, None, None, None, None]
    p = sorted(prices)
    med = p[n // 2] if n % 2 else (p[n // 2 - 1] + p[n // 2]) / 2
    return [n, sum(x < 100 for x in p) / n, sum(x <= 105 for x in p) / n, sum(x <= 110 for x in p) / n, med]


def pct_rank(hist, v):
    """hist 已排序；回傳 ≤ v 的比例。"""
    if v is None or not hist:
        return None
    return bisect_right(hist, v) / len(hist)


def main():
    expect = sys.argv[sys.argv.index('--expect') + 1] if '--expect' in sys.argv else None
    closed = closed_dates()
    dates = [d for d in archived_dates() if d not in closed]
    if not dates:
        sys.exit('沒有原始檔')
    first_seen, out = {}, {k: [] for k in ('all', 'traded', 'age60')}
    last_rows, prev_ref = None, {}
    for i, d in enumerate(dates):
        fd, rows = load(d)
        assert fd == d, f'{d} 檔內日期 {fd}'
        for r in rows:
            first_seen.setdefault(r['code'], i)
        ok = [r for r in rows if r['ref'] and r['ref'] > 0]
        out['all'].append(stats([r['ref'] for r in ok]))
        out['traded'].append(stats([r['close'] for r in rows if r['close'] and r['close'] > 0]))
        out['age60'].append(stats([r['ref'] for r in ok
                                   if first_seen[r['code']] == 0 or i - first_seen[r['code']] >= AGE_MIN]))
        if i == len(dates) - 1:
            last_rows = rows
            last_prev = prev_ref
        prev_ref = {r['code']: r['ref'] for r in ok}
    D = dates[-1]
    if expect and D != expect:
        sys.exit(f'最新原始檔為 {D}，不是預期的 {expect}')
    keys = ['n', 'lt100', 'le105', 'le110', 'med']
    series, today = {}, {}
    for v, rows in out.items():
        cols = list(zip(*rows))
        series[v] = {k: [None if x is None else round(x, 5) for x in cols[j]] for j, k in enumerate(keys)}
        t = {}
        for j, k in enumerate(keys):
            col = [x for x in cols[j] if x is not None]
            t[k] = cols[j][-1]
            if k != 'n':
                t[k + '_pct'] = pct_rank(sorted(col), cols[j][-1])
        le = cols[2]
        ch = [None if a is None or b is None else a - b for a, b in zip(le[20:], le[:-20])]
        chv = [x for x in ch if x is not None]
        t['chg20'] = ch[-1] if ch else None
        t['chg20_pct'] = pct_rank(sorted(chv), t['chg20'])
        t['extreme'] = t['le105'] is not None and t['le105'] >= EXTREME
        today[v] = {k: (round(x, 5) if isinstance(x, float) else x) for k, x in t.items()}
    # 歷史極端期間（主口徑）
    le = series['all']['le105']
    runs, s = [], None
    for i, x in enumerate(le + [None]):
        hit = x is not None and x >= EXTREME
        if hit and s is None:
            s = i
        if not hit and s is not None:
            runs.append([s, i - 1]); s = None
    eps = []
    for a, b in runs:
        if eps and a - eps[-1][1] - 1 <= MERGE_GAP:
            eps[-1][1] = b
        else:
            eps.append([a, b])
    episodes = []
    for a, b in eps:
        seg = le[a:b + 1]
        k = max(range(len(seg)), key=lambda j: seg[j])
        episodes.append({'s': dates[a], 'e': dates[b], 'days': b - a + 1, 'hit_days': sum(x >= EXTREME for x in seg if x is not None),
                         'peak': dates[a + k], 'peak_le105': seg[k], 'peak_lt100': series['all']['lt100'][a + k],
                         'peak_med': series['all']['med'][a + k], 'peak_n': series['all']['n'][a + k],
                         'ongoing': b == len(dates) - 1})
    now = dt.datetime.now(TPE).strftime('%Y-%m-%d %H:%M')
    meta = {'rule': RULE, 'date': D, 'updated': now, 'start': dates[0], 'days': len(dates),
            'extreme': {'le105': EXTREME, 'merge_gap': MERGE_GAP, 'status': '暫用 Elon 參考值，待 Ed 確認'},
            'source': '櫃買中心 RSta0113 轉(交)換公司債買賣斷交易行情表（等價）'}
    json.dump({**meta, 'dates': dates, 'series': series, 'today': today, 'episodes': episodes},
              open(os.path.join(ROOT, 'docs', 'cb.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    lst = []
    for r in last_rows:
        if not (r['ref'] and r['ref'] > 0):
            continue
        p0 = last_prev.get(r['code'])
        lst.append([r['code'], r['name'], r['ref'], r['close'], r['chg'],
                    None if not p0 else round(r['ref'] - p0, 2), int(r['units'] or 0),
                    None if first_seen[r['code']] == 0 else len(dates) - 1 - first_seen[r['code']] + 1])
    json.dump({**meta, 'cols': ['代號', '名稱', '參價', '收市', '漲跌', '參價變動', '成交張數', '掛牌交易日'], 'rows': lst},
              open(os.path.join(ROOT, 'docs', 'cb_list.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    t = today['all']
    print(f'{D}：{t["n"]} 檔，<100 {t["lt100"]:.1%}（{t["lt100_pct"]:.0%}），≤105 {t["le105"]:.1%}（{t["le105_pct"]:.0%}），'
          f'≤110 {t["le110"]:.1%}，中位數 {t["med"]:.2f}；20 日變化 {t["chg20"]:+.1%}（{t["chg20_pct"]:.0%}）；極端期間 {len(episodes)} 段')


if __name__ == '__main__':
    main()
