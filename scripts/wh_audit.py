"""權值高價股名單稽核包（供 Eve 複查）。先執行：
  WH_UNRESOLVED=max python3 scripts/wh_lists.py  → 產生 cache/wh_twse_detail_max.json 並將上限版名單另存
  python3 scripts/wh_lists.py                     → 正式版
用法：python3 wh_audit.py <上限版 wh_lists.json> <上限版 wh_share_events.json> <版本代號>
輸出 audit/<版本>_*.csv
"""
import csv, glob, gzip, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from mops_div_notice import parse_notice  # noqa: E402


def w(name, header, rows):
    p = os.path.join(ROOT, 'audit', name)
    with open(p, 'w', encoding='utf-8-sig', newline='') as f:
        cw = csv.writer(f); cw.writerow(header); cw.writerows(rows)
    return p


def main():
    max_lists, max_events, ver = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(os.path.join(ROOT, 'audit'), exist_ok=True)
    name = json.load(gzip.open(os.path.join(ROOT, 'cache', 'wh_px.json.gz'), 'rt', encoding='utf-8'))['name']
    L = json.load(open(os.path.join(ROOT, 'config', 'wh_lists.json')))
    LM = json.load(open(max_lists))
    D = json.load(open(os.path.join(ROOT, 'cache', 'wh_twse_detail.json')))
    DM = json.load(open(os.path.join(ROOT, 'cache', 'wh_twse_detail_max.json')))
    E = json.load(open(os.path.join(ROOT, 'cache', 'wh_share_events.json')))
    EM = json.load(open(max_events))
    r80 = set(json.load(open(os.path.join(ROOT, 'cache', 'wh_rank80.json'))))
    top = {c for v in L.values() for c, _ in v['twse']}

    # 1. 市值計算明細（每月上市前 60；Eve 指定的兩筆另列）
    rows = []
    for ym in sorted(D):
        for c, d in sorted(D[ym].items(), key=lambda x: x[1]['rank']):
            adj = d['q_shares'] * d['factor']
            ev = '；'.join(f"{a}×{r}({'除權' if k == 'ex' else '停止買賣'})" for a, r, k in d['events'])
            rows.append([ym, L[ym]['asof'], d['rank'], c, name.get(c, ''), d['close'], d['quarter'], d['q_shares'], ev, d['factor'],
                         round(adj), d['cap'], round(d['close'] * adj / 1e8, 1)])
    h = ['排名月', '排名日', '排名', '代號', '名稱', '排名日收盤', '季報期別(民國年季)', '季報普通股股數', '季底後股數事件(日期×倍率)',
         '事件倍率合計', '調整後股數', '市值(億)', '驗算市值=收盤×調整後股數(億)']
    w(f'{ver}_twse_mktcap_detail.csv', h, rows)
    w(f'{ver}_twse_mktcap_detail_eve_cases.csv', h, [r for r in rows if (r[0], r[3]) in {('202107', '8454'), ('202510', '3665')}])

    # 2. 略過事件清單（每事件一列；補件與現增並存者合併；出處欄全填）
    tw = {}
    for f in sorted(glob.glob(os.path.join(ROOT, 'archive', 'raw', 'twse_events', 'TWT49U_*.json'))):
        for r in json.load(open(f))['data']:
            m = re.match(r'(\d+)\D+(\d+)\D+(\d+)', r[0])
            tw[(r[1].strip(), '%d%02d%02d' % (int(m[1]) + 1911, int(m[2]), int(m[3])))] = (r, os.path.basename(f))
    notice = {}
    for f in glob.glob(os.path.join(ROOT, 'archive', 'raw', 'mops_div_notice', '*_*_*.html.gz')):
        if f.endswith('_list.html.gz'): continue
        p = parse_notice(f); notice.setdefault((os.path.basename(f)[:4], p['exdate']), []).append((os.path.basename(f), p))
    ov = json.load(open(os.path.join(ROOT, 'config', 'div_overrides.json')))
    ev_by = {}
    for u in E['unsplit']:
        if u[2] in ('stock_rate_missing', 'cash_capital_increase'):
            ev_by.setdefault((u[1], u[0]), set()).add(u[2])
    for (c, ds) in list(notice) + [(c, d) for c in ov if not c.startswith('_') for d in ov[c]]:
        if (c, ds) in tw: ev_by.setdefault((c, ds), set()).add('notice')
    rows = []
    for (c, ds), kinds in sorted(ev_by.items(), key=lambda x: (x[0][1], x[0][0])):
        r, src = tw[(c, ds)]
        fixed = 'notice' in kinds
        cats, srcs = [], [f'證交所除權除息計算結果表 TWT49U（archive/raw/twse_events/{src}）']
        if fixed:
            cats.append('已補件：配股率取自除權息基準日公告並通過參考價驗證')
            for fn, p in notice.get((c, ds), []):
                srcs.append(f"公告 archive/raw/mops_div_notice/{fn}：配股{p['stock']}元/股、現金{p['cash']}元/股")
            if c in ov and ds in ov[c]: srcs.append('手動補登 config/div_overrides.json：' + ov[c][ds]['source'])
        elif 'stock_rate_missing' in kinds:
            cats.append('仍缺配股率：不調整股數（上限敏感度見 sensitivity 檔）')
        if 'cash_capital_increase' in kinds:
            cats.append('含現金增資除權：現增新股不調整，待下季財報反映（Ed 2026-10-27）')
            srcs.append(f'判定依據：減除股利參考價 {r[10]} ≠ 除權息參考價 {r[4]}')
        rows.append([ds, c, name.get(c, ''), r[6].strip(), r[3], r[4], r[10], '是' if c in r80 else '否', '是' if c in top else '否',
                     '／'.join(cats), '；'.join(srcs)])
    hdr = ['除權息交易日', '代號', '名稱', '證交所類型', '除權息前收盤', '除權息參考價', '減除股利參考價', '曾進上市前80', '曾進上市前50', '處理', '出處']
    w(f'{ver}_skipped_events_all.csv', hdr, rows)
    w(f'{ver}_skipped_events_top80.csv', hdr, [r for r in rows if r[7] == '是'])

    # 3. 上限敏感度：逐事件上限倍率、逐月比較
    srows = []
    for u in sorted(E['unsplit']):
        if u[2] != 'stock_rate_missing': continue
        r, _ = tw[(u[1], u[0])]
        prev, dref = float(r[3].replace(',', '')), float((r[10] or r[4]).replace(',', ''))
        hit = [ym for ym in DM if u[1] in DM[ym]]
        srows.append([u[0], u[1], name.get(u[1], ''), r[6].strip(), r[3], r[10], round(prev / dref, 6), '是' if u[1] in r80 else '否',
                      min((DM[ym][u[1]]['rank'] for ym in hit), default='未進前60')])
    w(f'{ver}_sensitivity_events.csv', ['除權息交易日', '代號', '名稱', '類型', '除權息前收盤', '減除股利參考價',
                                       '上限倍率=前收盤÷減除股利參考價（假設全為配股、無現金股利）', '曾進上市前80(正式版)',
                                       '上限版下最佳排名（前60內）'], srows)
    unres = {r[1] for r in srows}
    mrows = []
    for ym in sorted(L):
        a, b = [c for c, _ in L[ym]['twse']], [c for c, _ in LM[ym]['twse']]
        cap50 = L[ym]['twse'][49][1]
        best = sorted(((DM[ym][c]['rank'], c, DM[ym][c]['cap']) for c in DM[ym] if c in unres))
        mrows.append([ym, L[ym]['asof'], '是' if set(a) == set(b) else '否', '是' if a == b else '否',
                      '是' if [c for c, _ in L[ym]['hp']] == [c for c, _ in LM[ym]['hp']] else '否', cap50,
                      (f'{best[0][1]}{name.get(best[0][1], "")} 第{best[0][0]}名 {best[0][2]}億' if best else '前60內無')])
    w(f'{ver}_sensitivity_months.csv', ['排名月', '排名日', '上市前50成分相同', '上市前50排序相同', '高價股前30排序相同',
                                       '正式版第50名市值(億)', '上限版前60內排名最高的未解事件公司'], mrows)
    print('detail', len(D), 'skipped', len(rows), 'top80', sum(r[7] == '是' for r in rows), 'sens events', len(srows),
          'months', len(mrows), 'all same', all(r[2] == r[3] == r[4] == '是' for r in mrows))


if __name__ == '__main__':
    main()
