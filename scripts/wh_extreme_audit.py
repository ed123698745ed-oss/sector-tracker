"""市場狀態補證：逐日截斷重算、狀態機邊界表、可配置事件表、年度切換統計。

不改門檻、不關推播。產出寫到 docs/wh-market-state-evidence/。

  python3 scripts/wh_extreme_audit.py
  python3 scripts/wh_extreme_audit.py pit --quick
  python3 scripts/wh_extreme_audit.py yearly
  python3 scripts/wh_extreme_audit.py events
  python3 scripts/wh_extreme_audit.py boundaries

完整逐日截斷會對每個交易日呼叫一次 wh_extreme.compute（約數分鐘）。
"""
import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wh_extreme
from wh_prices import is_common

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'wh-market-state-evidence')
TPE = timezone(timedelta(hours=8))
STATE_KEY = {0: 'normal', -1: 'down', 1: 'up', 2: 'conc'}


def _now():
    return datetime.now(TPE).isoformat(timespec='seconds')


def _dump(name, obj):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return path


def _write(name, text):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def load_wh():
    with open(os.path.join(ROOT, 'docs', 'wh.json'), encoding='utf-8') as f:
        return json.load(f)


def load_inputs(w):
    """成交值與集中度只讀當日 data/quotes。普通股過濾與 wh_prices.is_common 相同。

    加權指數水準用 wh.json 的 taiex（MI_INDEX／FMTQIK 收盤），不用 quotes 裡的 taiex。
    quotes['taiex'] 是加權漲跌%，不是指數點位。
    """
    dates = w['dates']
    allg = {k: w['groups']['all'][k] for k in ('n', 'ld', 'lu', 'dd')}
    turnover, conc = [], []
    for ds in dates:
        q = json.load(open(os.path.join(ROOT, 'data', 'quotes', ds + '.json'), encoding='utf-8'))
        vals = [(v[1], c) for c, v in q['q'].items() if is_common(c) and len(v) > 1 and v[1] is not None]
        tot = sum(x for x, _ in vals)
        turnover.append(tot or None)
        ex = sorted((x for x, c in vals if c != '2330'), reverse=True)
        s = sum(ex)
        conc.append(sum(ex[:5]) / s if ex and s else None)
    return dates, w['taiex'], allg, turnover, conc


def _series_hash(rows):
    h = hashlib.sha256()
    for row in rows:
        h.update(repr(row).encode())
        h.update(b'\n')
    return h.hexdigest()


def _fmt_num(v):
    if v is None:
        return 'null'
    if isinstance(v, float):
        return repr(v)
    return str(v)


def counts(w):
    ext, dates = w['ext'], w['dates']
    scored = sum(v is not None for v in ext['down'])
    abnormal = sum(s != 0 for s in ext['state'])
    first = next((dates[i] for i, v in enumerate(ext['down']) if v is not None), None)
    by = Counter(s for i, s in enumerate(ext['state']) if ext['down'][i] is not None)
    return {
        'stock_date': w.get('stock_date'),
        'trading_days': len(dates),
        'first_date': dates[0],
        'last_date': dates[-1],
        'first_scored_date': first,
        'scored_days': scored,
        'abnormal_days': abnormal,
        'abnormal_share': None if not scored else abnormal / scored,
        'state_days_on_scored': {STATE_KEY[k]: by[k] for k in (0, -1, 1, 2)},
        'rule': wh_extreme.RULE_ID,
        'definition': '有分數日＝down 不是 null。stock_date=20261029 時為 5093 日，其中 state≠0 為 695 日（13.65%）。',
    }


def run_yearly(w):
    dates, ext = w['dates'], w['ext']
    y0, y1 = int(dates[0][:4]), int(dates[-1][:4])
    by = {}
    for y in range(y0, y1 + 1):
        by[str(y)] = {
            'year': str(y), 'trading_days': 0, 'scored_days': 0, 'abnormal_days': 0, 'switches': 0,
            'states': {'normal': 0, 'down': 0, 'up': 0, 'conc': 0},
            'first_date': None, 'last_date': None,
        }
    st, dn = ext['state'], ext['down']
    for i, d in enumerate(dates):
        rec = by[d[:4]]
        rec['trading_days'] += 1
        rec['first_date'] = rec['first_date'] or d
        rec['last_date'] = d
        if i > 0 and st[i] != st[i - 1]:
            rec['switches'] += 1
        if dn[i] is None:
            continue
        rec['scored_days'] += 1
        rec['states'][STATE_KEY[st[i]]] += 1
        if st[i] != 0:
            rec['abnormal_days'] += 1
    rows = []
    for y in range(y0, y1 + 1):
        rec = by[str(y)]
        flags = []
        if rec['trading_days'] == 0:
            flags.append('缺資料')
        elif rec['scored_days'] == 0:
            flags.append('無分數')
            flags.append('切換零次')
        else:
            if rec['scored_days'] < rec['trading_days']:
                flags.append('分數不完整')
            else:
                flags.append('檔內交易日皆有分數')
            if rec['switches'] == 0:
                flags.append('切換零次')
        if rec['first_date'] == dates[0] and rec['first_date'][4:] > '0110':
            flags.append('不完整年（序列起點）')
        if rec['last_date'] == dates[-1] and rec['last_date'][4:] < '1201':
            flags.append('不完整年（序列終點，資料未到年底）')
        rec['flags'] = flags
        rec['note'] = '；'.join(flags)
        rows.append(rec)
    scored_years = [r for r in rows if r['scored_days'] > 0]
    switch_years = [r for r in scored_years if r['switches'] > 0]
    zero_years = [r['year'] for r in scored_years if r['switches'] == 0]
    total = sum(r['switches'] for r in rows)
    c = counts(w)
    summary = {
        'generated_at': _now(),
        'stock_date': w.get('stock_date'),
        'rule': wh_extreme.RULE_ID,
        'switch_definition': '切換＝相鄰兩個交易日（wh.json dates 順序）state 不同，計入新狀態那天的西元年。暖機期間 state 維持 0，不產生切換。這與推播用的 state[-2]≠state[-1] 同一口徑。',
        'calendar_limit': '中間年份是否缺某個交易所交易日，未與交易所行事曆逐日勾稽。缺資料只用於檔內完全沒有該年日期的年份。',
        'total_switches': total,
        'years_in_file': len(rows),
        'years_with_scores': len(scored_years),
        'years_with_at_least_one_switch': len(switch_years),
        'zero_switch_years_with_scores': zero_years,
        'mean_per_scored_year_including_zeros': None if not scored_years else total / len(scored_years),
        'mean_per_year_that_had_a_switch': None if not switch_years else total / len(switch_years),
        'about_8_1': '約 8.1 次／年對應「有至少一次切換的年份」當分母（零次年排除）。全部有分數年份當分母會更低。零次年不是缺資料。',
        'snapshot': c,
        'years': rows,
    }
    _dump('yearly.json', summary)
    lines = [
        '# 市場狀態年度切換',
        '',
        f"- 資料日：`{w.get('stock_date')}`；規則 `{wh_extreme.RULE_ID}`",
        f"- 有分數日 {c['scored_days']}、非常態 {c['abnormal_days']}（{c['abnormal_share'] * 100:.2f}%）、首次有分數 {c['first_scored_date']}",
        f"- 切換合計 {total} 次",
        f"- 有分數年 {len(scored_years)} 年（含切換零次）平均 {summary['mean_per_scored_year_including_zeros']:.3f} 次／年",
        f"- 有至少一次切換的 {len(switch_years)} 年平均 {summary['mean_per_year_that_had_a_switch']:.3f} 次／年（約 8.1 的分母是這一個，不是全部有資料年）",
        f"- 有分數但切換零次：{('、'.join(zero_years) if zero_years else '無')}。這些年不是缺資料。",
        '',
        summary['switch_definition'],
        '',
        summary['calendar_limit'],
        '',
        '| 年 | 交易日 | 有分數日 | 非常態日 | 常態 | 下跌 | 上漲 | 集中 | 切換 | 標記 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |',
    ]
    for r in rows:
        stt = r['states']
        lines.append(
            f"| {r['year']} | {r['trading_days']} | {r['scored_days']} | {r['abnormal_days']} | "
            f"{stt['normal']} | {stt['down']} | {stt['up']} | {stt['conc']} | {r['switches']} | {r['note']} |"
        )
    lines.append('')
    _write('yearly.md', '\n'.join(lines))
    return summary


def _window(dates, ext, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    scored = [i for i in idx if ext['down'][i] is not None]
    n = len(scored)
    days = {k: 0 for k in ('normal', 'down', 'up', 'conc')}
    for i in scored:
        days[STATE_KEY[ext['state'][i]]] += 1
    abn = n - days['normal']

    def share(k):
        return None if n == 0 else days[k] / n

    return {
        'start': start,
        'end': end,
        'start_inclusive': True,
        'end_inclusive': True,
        'trading_days': len(idx),
        'valid_scored_days': n,
        'unscored_trading_days': len(idx) - n,
        'first_trading_day': dates[idx[0]] if idx else None,
        'last_trading_day': dates[idx[-1]] if idx else None,
        'days': days,
        'abnormal_days': abn,
        'share_of_valid': {k: share(k) for k in days},
        'abnormal_share': None if n == 0 else abn / n,
    }


def run_events(w):
    cfg = json.load(open(os.path.join(ROOT, 'config', 'wh_extreme_events.json'), encoding='utf-8'))
    dates, ext = w['dates'], w['ext']
    ed_rows = []
    for row in cfg['ed_review']['rows']:
        item = dict(row)
        item['status'] = '原交審窗未驗證／待 Ed 補起訖'
        item['computed'] = None
        if row.get('start') and row.get('end'):
            item['status'] = '已有起迄，依閉區間重算（仍須 Ed 確認這就是原交審窗）'
            item['computed'] = _window(dates, ext, row['start'], row['end'])
        ed_rows.append(item)
    eve_rows = []
    for row in cfg['eve_custom_windows']['rows']:
        item = dict(row)
        item['status'] = cfg['eve_custom_windows']['status']
        item['computed'] = _window(dates, ext, row['start'], row['end'])
        focus = { -1: 'down', 1: 'up', 2: 'conc', 0: 'normal'}.get(row.get('focus_state'))
        comp = item['computed']
        item['focus_share'] = None if not focus else comp['share_of_valid'][focus]
        eve_rows.append(item)
    out = {
        'generated_at': _now(),
        'stock_date': w.get('stock_date'),
        'rule': wh_extreme.RULE_ID,
        'endpoint': cfg['endpoint'],
        'snapshot': counts(w),
        'not_equivalent': cfg['not_equivalent'],
        'ed_review': {'status': cfg['ed_review']['status'], 'note': cfg['ed_review']['note'], 'rows': ed_rows},
        'eve_custom_windows': {
            'status': cfg['eve_custom_windows']['status'],
            'note': cfg['eve_custom_windows']['note'],
            'rows': eve_rows,
        },
    }
    _dump('events.json', out)
    lines = [
        '# 市場狀態事件表',
        '',
        '> **2026-10-30 起改用價格規則。** Ed 2026-10-30 表示事件命中率不是主要標準，改以「抓到劇烈快速下跌／急漲波段、盡量抓到頂部，搭配期間累積漲跌」判斷；'
        '下表 Ed 列為舊版百分位規則調參時的宣稱占比（起迄未保存），僅留作歷史紀錄，不再當成本規則的驗收依據。',
        '',
        '原交審窗未驗證／待 Ed 補起訖。下面自訂窗是 Eve 抽查對照，不是原表。',
        '',
        cfg['not_equivalent']['text'],
        '',
        '## 欄位',
        '',
        f"- 端點：{cfg['endpoint']['calendar']}",
        f"- 有效交易日：{cfg['endpoint']['valid_day']}",
        f"- 天數與占比：{cfg['endpoint']['state_days']} {cfg['endpoint']['share']}",
        f"- 資料版本：stock_date=`{w.get('stock_date')}`，規則 `{wh_extreme.RULE_ID}`",
        '',
        '## Ed 交審列（起迄未補，不重算）',
        '',
        '| id | 標籤 | 宣稱占比 | 起 | 迄 | 狀態 |',
        '| --- | --- | ---: | --- | --- | --- |',
    ]
    for row in ed_rows:
        lines.append(
            f"| {row['id']} | {row['label']} | {row.get('claimed_share')} | {row.get('start') or '—'} | {row.get('end') or '—'} | {row['status']} |"
        )
    lines += [
        '',
        '## Eve 自訂日曆窗（不是原交審表）',
        '',
        '| id | 標籤 | 交易日 | 有效日 | 下跌天 | 上漲天 | 集中天 | 聚焦狀態占比 |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for row in eve_rows:
        c = row['computed']
        share = row['focus_share']
        share_s = '—' if share is None else f'{share * 100:.1f}%'
        lines.append(
            f"| {row['id']} | {row['label']} | {c['trading_days']} | {c['valid_scored_days']} | "
            f"{c['days']['down']} | {c['days']['up']} | {c['days']['conc']} | {share_s} |"
        )
    lines.append('')
    _write('events.md', '\n'.join(lines))
    return out


def run_boundaries():
    table = wh_extreme.boundary_rows()
    _dump('state-machine.json', {'generated_at': _now(), **table})
    lines = [
        '# 市場狀態狀態機邊界案例',
        '',
        f"規則 `{table['rule']}`。全部案例 {'通過' if table['pass'] else '有落差'}。",
        '價格規則：窗口縮為 3 日以便手算；門檻與正式規則相同（下跌 −9%／反彈 6%，上漲 +20%／回落 5%）。',
        '恰等於門檻的收盤以同一乘式產生；恰差一點用 `math.nextafter`。',
        '',
        '| id | 組 | 日 | 前態 | 收盤 | 距窗高 | 距窗低 | 預期 | 實際 | 相符 | 說明 |',
        '| --- | --- | ---: | ---: | ---: | --- | --- | ---: | ---: | --- | --- |',
    ]
    for r in table['rows']:
        lines.append(
            f"| {r['id']} | {r['group']} | {r['day']} | {r['prev']} | {r['price']!r} | {_fmt_num(r['dd'])} | {_fmt_num(r['ru'])} | "
            f"{r['expected']} | {r['actual']} | {str(r['match']).lower()} | {r['desc']} |"
        )
    lines.append('')
    _write('state-machine.md', '\n'.join(lines))
    if not table['pass']:
        raise SystemExit('狀態機邊界案例未通過')
    return table


# 截斷重算之外、無法驗證時點的範圍。只寫 repo 內查得到的事實；期間以現存檔名範圍為準。
UNVERIFIABLE_SCOPE = [
    {
        'field': 'groups.all.ld／lu（5 日跌停、漲停家數占比的分子）',
        'period': '全期（20040211～資料日）',
        'source': 'cache/wh_px.json.gz 的 lim（wh_prices.py 由 data/quotes、archive/raw/twse_events、twse_newlisting、tpex 判定）',
        'reason': '沒有逐日前綴重跑 wh_prices。除權息／恢復買賣日的漲跌停價取自 twse_events，該目錄由 whext.yml 事後批次抓取，不是各日當下取得；判定規則也經多次複核修訂（git log）。',
    },
    {
        'field': 'groups.all.n（當日有效家數，占比分母）',
        'period': '全期',
        'source': 'wh_build.py 以 cache/wh_px.json.gz 計數',
        'reason': '同上，未逐日前綴重跑；母體是現存行情檔裡符合 is_common 的代號，不是當日凍結名單。',
    },
    {
        'field': 'groups.all.dd（離近 250 日高點 ≥20% 占比）',
        'period': '全期；個股上市未滿 250 日不計',
        'source': 'wh_build.py 的還原價（以每日漲跌% 連乘）與盤中最高價',
        'reason': '還原價以全期一次建置，未逐日前綴重跑。滾動窗依程式是往回看，但沒有實際截斷驗證；現存漲跌% 可能含事後補算的參考價。',
    },
    {
        'field': 'taiex（加權指數點位）',
        'period': '20040211～20081231',
        'source': 'archive/raw/twse_fmtqik 月檔（現存 200402～201412）',
        'reason': '月檔由 whext.yml 事後下載；公式只讀當日列，但無法證明月檔內容與當日公布值相同。',
    },
    {
        'field': 'taiex（加權指數點位）',
        'period': '20090101～資料日',
        'source': 'archive/raw/twse/YYYYMMDD.json.gz（MI_INDEX）；缺檔或缺列時退回 FMTQIK',
        'reason': '沒有標記哪些日子實際用了退回值；原始檔抓取時間未逐日記錄。',
    },
    {
        'field': 'turnover、conc（成交值、前五大集中度）',
        'period': '全期',
        'source': 'data/quotes/YYYYMMDD.json',
        'reason': '截斷重算有用到這兩條，證明 compute 不讀未來；但行情檔本身可能是 backfill 補抓或修正後版本，repo 未保存各日公布當下版本。',
    },
    {
        'field': '母體口徑（上市 vs 上市櫃）',
        'period': '20070702 以前',
        'source': 'archive/raw/tpex 現存檔',
        'reason': '頁面註記櫃買資料 2007/07 起，此前全市場欄位僅上市普通股。這是口徑變化，不是前視；未另做上市-only 的對照重算。',
    },
    {
        'field': '盤中值',
        'period': '全期',
        'source': '無',
        'reason': '收盤檔公布前的數值沒有另存，無從比較盤中與收盤後判定。',
    },
    {
        'field': 'Ed 原交審事件表（起迄、母體、資料版本）',
        'period': '交審表所列各窗',
        'source': '不在 repo',
        'reason': '舊版調參宣稱占比的起迄未保存；2026-10-30 起不再作為驗收依據，見 events.md。',
    },
]


def _pit_one(i, dates, taiex, allg, turnover, conc):
    sl = slice(0, i + 1)
    sub = {k: allg[k][sl] for k in ('n', 'ld', 'lu', 'dd')}
    return wh_extreme.compute(dates[sl], taiex[sl], sub, turnover[sl], conc[sl])


def run_pit(w, quick=False):
    dates, taiex, allg, turnover, conc = load_inputs(w)
    full = wh_extreme.compute(dates, taiex, allg, turnover, conc)
    pub = w['ext']
    published_mismatch = []
    for key in ('state', 'down', 'up', 'conc'):
        n = sum(a != b for a, b in zip(pub[key], full[key]))
        if n:
            published_mismatch.append({'series': key, 'count': n})
    n = len(dates)
    if quick:
        indexes = sorted(set([0, n - 1] + list(range(0, n, 50))))
    else:
        indexes = list(range(n))
    diffs = []
    # 逐日把輸入截到該日（含）再呼叫正式 compute，比對完整序列的同一天。
    workers = min(4, os.cpu_count() or 1)
    if workers > 1 and len(indexes) > 100:
        import multiprocessing as mp
        ctx = mp.get_context('fork')
        payload = (dates, taiex, allg, turnover, conc, full, indexes)
        with ctx.Pool(processes=workers, initializer=_pit_init, initargs=(payload,)) as pool:
            for rec in pool.imap_unordered(_pit_worker, range(len(indexes)), chunksize=40):
                if rec:
                    diffs.append(rec)
    else:
        for i in indexes:
            rec = _compare_day(i, dates, taiex, allg, turnover, conc, full)
            if rec:
                diffs.append(rec)
    diffs.sort(key=lambda r: r['i'])
    out = {
        'generated_at': _now(),
        'stock_date': w.get('stock_date'),
        'rule': wh_extreme.RULE_ID,
        'baseline_commit': wh_extreme.TH_VERSIONS[-1].get('introduced_commit'),
        'quick': quick,
        'method': '對每個受檢交易日 i，只保留 dates、taiex、全市場 n/ld/lu/dd、turnover、conc 的前綴 [:i+1]（含 i），呼叫 wh_extreme.compute，比對一次完整序列在 i 的 state 與三位小數分數。',
        'checked_days': len(indexes),
        'series_days': n,
        'mismatch_days': len(diffs),
        'conclusion': '零差異' if not diffs and not published_mismatch else '有差異',
        'published_wh_json_vs_full_recompute': published_mismatch or '零差異',
        'diffs': diffs,
        'hashes': {
            'published_state_scores': _series_hash(
                (dates[i], pub['state'][i], pub['down'][i], pub['up'][i], pub['conc'][i]) for i in range(n)),
            'recomputed_state_scores': _series_hash(
                (dates[i], full['state'][i], full['down'][i], full['up'][i], full['conc'][i]) for i in range(n)),
            'turnover': _series_hash(turnover),
            'conc': _series_hash(conc),
        },
        'inputs': {
            'dates_taiex_breadth': 'docs/wh.json 的 dates、taiex、groups.all 的 n／ld／lu／dd',
            'turnover_conc': 'data/quotes/YYYYMMDD.json 當日成交金額（億）。普通股＝wh_prices.is_common（4 碼數字、不以 0 開頭、排除 91）。集中度排除 2330 後取前五大成交值占其餘成交值。',
            'taiex_not_from_quotes_field': 'data/quotes 的 taiex 欄是加權漲跌%，不是指數點位，不進入 compute。',
        },
        'snapshot': counts(w),
        'unverifiable': [
            '沒有各歷史日收盤當下的行情、指數、母體快照。現在的 data/quotes 與 archive/raw 可能含事後修正、補檔與除權息／減資／分割參考價補算。截斷重算證明的是「這份現存輸入」下，分數與狀態只用到該日（含）為止，不能證明當時公布的版本與現在檔案相同。',
            '普通股母體是現存每日行情檔裡符合 is_common 的代號，不是當日凍結的指數成分或當時的上市櫃名單影像。',
            '2009 年以前加權指數取自月檔 FMTQIK 的當日收盤列。公式沒有讀該日之後的列，但檔案本身可能是後來才下載或覆蓋的。',
            '跌停家數、離高點分布等 groups.all 欄位沿用已建置的 wh.json，本次沒有把 wh_prices／wh_build 對每個前綴再跑一次。程式裡滾動窗是往回看（含當日或前 N 日，不含未來日）；這段上游沒有做逐日截斷重跑。',
            '同一交易日盤中、收盤檔公布前的數值沒有另存。狀態只在該日 quotes 檔存在後由整日資料計算。',
            'Ed 交審事件的原始起迄與當時資料版本不在 repo，見 events.md。',
        ],
        'unverifiable_scope': UNVERIFIABLE_SCOPE,
    }
    _dump('pit.json', out)
    lines = [
        '# 時點／前視：逐日截斷重算',
        '',
        f"- 結論：**{out['conclusion']}**",
        f"- 受檢日 {out['checked_days']}／序列 {out['series_days']}；與發布 wh.json 的完整重算：{out['published_wh_json_vs_full_recompute']}",
        f"- 資料日 `{w.get('stock_date')}`，規則 `{wh_extreme.RULE_ID}`",
        '',
        out['method'],
        '',
        '## 無法驗證',
        '',
    ]
    for item in out['unverifiable']:
        lines.append(f'- {item}')
    lines += [
        '',
        '## 無法驗證範圍',
        '',
        '上面的截斷重算只對 `wh_extreme.compute` 這一層做。'
        '**沒有**對 `wh_prices.py`／`wh_build.py` 逐日前綴重跑（`wh_prices` 一次讀入全部 `data/quotes` 寫成單一 `cache/wh_px.json.gz`，'
        '`wh_build` 再以全期還原價與現行名單、事件表建置），所以下列欄位、期間、資料源的時點性質未經驗證：',
        '',
        '| 欄位 | 期間 | 資料源 | 為何無法驗證 |',
        '| --- | --- | --- | --- |',
    ]
    for r in out['unverifiable_scope']:
        lines.append(f"| {r['field']} | {r['period']} | {r['source']} | {r['reason']} |")
    lines.append('')
    if diffs:
        lines.append('## 差異')
        lines.append('')
        for rec in diffs[:50]:
            lines.append(f"- {rec['date']} full={rec['full']} truncated={rec['truncated']}")
        lines.append('')
    _write('pit.md', '\n'.join(lines))
    if diffs or published_mismatch:
        raise SystemExit('截斷重算或發布序列比對有差異')
    return out


_PIT = {}


def _pit_init(payload):
    global _PIT
    dates, taiex, allg, turnover, conc, full, indexes = payload
    _PIT = {
        'dates': dates, 'taiex': taiex, 'allg': allg, 'turnover': turnover, 'conc': conc,
        'full': full, 'indexes': indexes,
    }


def _compare_day(i, dates, taiex, allg, turnover, conc, full):
    got = _pit_one(i, dates, taiex, allg, turnover, conc)
    keys = ('state', 'dd', 'ru', 'down', 'up', 'conc')
    full_row = tuple(full[k][i] for k in keys)
    trunc_row = tuple(got[k][-1] for k in keys)
    if trunc_row != full_row:
        return {'i': i, 'date': dates[i], 'full': list(full_row), 'truncated': list(trunc_row)}
    return None


def _pit_worker(k):
    i = _PIT['indexes'][k]
    return _compare_day(i, _PIT['dates'], _PIT['taiex'], _PIT['allg'], _PIT['turnover'], _PIT['conc'], _PIT['full'])


def write_readme():
    text = """# 市場狀態補證產出

由 `python3 scripts/wh_extreme_audit.py` 產生。現行規則 2026-10-30（價格規則）；LINE 推播依 Ed 2026-10-30 指示暫停。

| 檔案 | 內容 |
| --- | --- |
| pit.md / pit.json | 逐日截斷重算 vs 完整序列。零差異或差異清單。並說明無法驗證的範圍。 |
| state-machine.md / state-machine.json | 進入／退出恰等於門檻、同時達標、維持與競合、退出切換、暖機與缺值。含輸入、前態、預期、實際。 |
| events.md / events.json | 各自訂窗的狀態天數。舊版調參宣稱占比僅留作歷史紀錄，不是現行規則的驗收依據。 |
| yearly.md / yearly.json | 檔內每一年的切換次數，含零次、無分數、不完整年。5093／695 口徑在 snapshot。 |
| notify.md / notify.json | 推播 dry-run 證據（mock push、不連網）：狀態變化、不變、同日重跑去重、失敗重試、未就緒、ledger 與 git 提交失敗。由 `python3 scripts/wh_notify_evidence.py` 產生。 |

> 現行規則的檢視重點是各段非常態的波段起點、極值與累積漲跌（頁面「歷次非常態期間」表），不是事件占比。

pit.md 的「無法驗證範圍」列出沒有對 `wh_prices`／`wh_build` 逐日前綴重跑的欄位、期間與資料源。

事件窗若要改，編輯 `config/wh_extreme_events.json` 後重跑。不要把自訂窗結果寫進 `ed_review` 列。

推播核對見 `scripts/wh_notify.py` 檔頭與 `docs/wh-market-state-rules.md`。試跑：

```
python3 scripts/wh_notify.py --dry-run
python3 scripts/wh_notify.py --preview-test
python3 scripts/wh_notify_evidence.py
```

`--preview-test` 的訊息帶「測試」，不會送出。
"""
    _write('README.md', text)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('cmd', nargs='?', default='all', choices=('all', 'pit', 'yearly', 'events', 'boundaries'))
    p.add_argument('--quick', action='store_true', help='截斷重算只抽樣（每 50 日加首尾）')
    args = p.parse_args(argv)
    w = load_wh()
    if args.cmd in ('all', 'boundaries'):
        run_boundaries()
        print('boundaries ok')
    if args.cmd in ('all', 'yearly'):
        s = run_yearly(w)
        print('yearly switches', s['total_switches'], 'mean_with_switch_years', round(s['mean_per_year_that_had_a_switch'], 3))
    if args.cmd in ('all', 'events'):
        run_events(w)
        print('events ok')
    if args.cmd in ('all', 'pit'):
        out = run_pit(w, quick=args.quick)
        print('pit', out['conclusion'], 'checked', out['checked_days'])
    if args.cmd == 'all':
        write_readme()
    return 0


if __name__ == '__main__':
    sys.exit(main())
