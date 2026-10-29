"""權值高價股歷史延伸（2004/02～2014/12）稽核包，供 Eve 複查。先執行 wh_prices.py、wh_lists.py、wh_build.py。
輸出 audit/EXT_*.csv（UTF-8 BOM，Excel 可直接開）
"""
import csv, glob, gzip, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'audit')
END = '201412'


def w(name, header, rows):
    p = os.path.join(OUT, name)
    with open(p, 'w', encoding='utf-8-sig', newline='') as f:
        cw = csv.writer(f); cw.writerow(header); cw.writerows(rows)
    print(name, len(rows))


def roc(s):
    m = re.match(r'\s*(\d+)\D+(\d+)\D+(\d+)', s)
    return '%d%02d%02d' % (int(m[1]) + 1911, int(m[2]), int(m[3]))


def main():
    os.makedirs(OUT, exist_ok=True)
    px = json.load(gzip.open(os.path.join(ROOT, 'cache', 'wh_px.json.gz'), 'rt', encoding='utf-8'))
    name, dates = px['name'], px['dates']
    L = json.load(open(os.path.join(ROOT, 'config', 'wh_lists.json')))
    D = json.load(open(os.path.join(ROOT, 'cache', 'wh_twse_detail.json')))
    E = json.load(open(os.path.join(ROOT, 'cache', 'wh_share_events.json')))
    yms = [k for k in sorted(L) if k <= END]

    # 1. 三組名單
    rows = []
    for ym in yms:
        v = L[ym]
        for g, lab in (('twse', '上市市值前50'), ('otc', '上櫃市值前30'), ('hp', '高價股前30')):
            for i, (c, x) in enumerate(v.get(g, []), 1):
                rows.append([ym, v['asof'], lab, i, c, name.get(c, ''), x])
    w('EXT_lists_200402_201412.csv', ['使用月份前一月(排名月)', '排名日', '組別', '名次', '代號', '名稱', '市值(億)或收盤價'], rows)

    # 2. 上市前 60 市值計算明細
    rows = []
    for ym in yms:
        for c, r in sorted(D.get(ym, {}).items(), key=lambda x: x[1]['rank']):
            rows.append([ym, L[ym]['asof'], r['rank'], c, name.get(c, ''), r['close'], r['q_shares'], r['quarter'], r['factor'],
                         ';'.join('%s×%.6f(%s)' % (a, b, k) for a, b, k in r['events']), r['cap'], 'Y' if r['rank'] <= 50 else ''])
    w('EXT_twse_mktcap_top60_detail.csv', ['排名月', '排名日', '名次', '代號', '名稱', '收盤', '發行股數(MI_QFIIS)', '股數來源日',
                                           '事件補正倍率', '補正事件(日期×倍率)', '市值(億)', '入選前50'], rows)

    # 3. 2004～2014 股數事件（含舊格式解析）
    rows = []
    for fp in sorted(glob.glob(os.path.join(ROOT, 'archive', 'raw', 'twse_events', '*.json'))):
        kind, yy = os.path.basename(fp)[:6], os.path.basename(fp)[7:11]
        if yy > '2014': continue
        j = json.load(open(fp)); f = [x.strip() for x in j.get('fields') or []]
        for r in j.get('data') or []:
            ds, c = roc(r[0]), r[1].strip()
            applied = [x for x in E['events'].get(c, []) if x[0] == ds]
            extra = ''
            if '息值' in f and '權值' in f: extra = '權值=%s 息值=%s' % (r[f.index('權值')], r[f.index('息值')])
            elif '權/息' in f: extra = '類別=%s' % r[f.index('權/息')]
            rows.append([ds, kind, c, r[2].strip(), r[3], r[4], extra, '%.6f' % applied[0][1] if applied else '', applied[0][2] if applied else ''])
    w('EXT_share_events_2004_2014.csv', ['日期', '表別', '代號', '名稱', '前收盤', '參考價', '原始欄位', '採用股數倍率', '類型'], rows)

    # 4. 未調整／警示事件
    rows = [[ds, c, name.get(c, ''), why] for ds, c, why in E['unsplit'] if ds[:6] <= END]
    w('EXT_unadjusted_events_2004_2014.csv', ['日期', '代號', '名稱', '原因'], rows)

    # 5. 有收盤但無漲跌%（當日不計入漲跌與還原價）的股票日
    rows = []
    import collections
    why_n = collections.Counter()
    ev = {}
    for fp in glob.glob(os.path.join(ROOT, 'archive', 'raw', 'twse_events', '*.json')):
        for r in json.load(open(fp)).get('data') or []:
            ev[(roc(r[0]), r[1].strip())] = os.path.basename(fp)[:6]
    for i, ds in enumerate(dates):
        if ds[:6] > END: break
        q = json.load(open(os.path.join(ROOT, 'data', 'quotes', ds + '.json')))['q']
        miss = [c for c, a in px['px'].items() if a[i] and c not in q]
        if not miss: continue
        raw = {}
        for m in ('twse', 'tpex'):
            p = os.path.join(ROOT, 'archive', 'raw', m, ds + '.json.gz')
            if not os.path.exists(p): continue
            for t in json.load(gzip.open(p)).get('tables') or []:
                f = [x.strip() for x in t.get('fields') or []]
                k = '漲跌(+/-)' if m == 'twse' else '漲跌'
                if k in f and ('證券代號' in f or '代號' in f):
                    for r in t.get('data') or []:
                        raw[r[0].strip()] = re.sub('<[^>]+>', '', r[f.index(k)]).strip()
        for c in miss:
            a = px['px'][c]; mk = {'t': '上市', 'o': '上櫃'}.get(px['mk'][c][i], '')
            prev = a[i - 1] if i else None; sg = raw.get(c, '')
            if not prev: why = '前一交易日無收盤（前日無成交、新上市首日、停止買賣後恢復、轉市場）'
            elif (ds, c) in ev: why = '證交所事件日（%s）查無參考價' % ev[(ds, c)]
            elif mk == '上市' and sg == 'X': why = '上市不比價（X）且查無參考價'
            elif mk == '上櫃' and '除' in sg: why = '上櫃除權息日查無參考價'
            else: why = '其他（原始漲跌欄：%s）' % sg
            why_n[why.split('（')[0]] += 1
            rows.append([ds, c, name.get(c, ''), mk, prev or '', a[i], sg, why])
    w('EXT_days_without_return.csv', ['日期', '代號', '名稱', '當日市場', '前一日收盤', '當日收盤', '原始漲跌欄', '原因'], rows)
    tot = sum(1 for i, ds in enumerate(dates) if ds[:6] <= END for c, a in px['px'].items() if a[i])
    print('無漲跌%股票日', len(rows), '／有收盤股票日', tot, '=%.3f%%' % (len(rows) / tot * 100), dict(why_n))

    # 6. 每日全市場統計（供抽查）
    W = json.load(open(os.path.join(ROOT, 'docs', 'wh.json')))
    a = W['groups']['all']; rows = []
    for i, ds in enumerate(W['dates']):
        if ds[:6] > END: break
        rows.append([ds, W['taiex'][i], a['n'][i], a['up'][i], a['flat'][i], a['down'][i], a['lu'][i], a['ld'][i]])
    w('EXT_daily_breadth_2004_2014.csv', ['日期', '加權指數', '有效家數', '上漲', '平盤', '下跌', '漲停', '跌停'], rows)


if __name__ == '__main__':
    main()
