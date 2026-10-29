"""權值與高價股觀察分頁：從原始收盤行情建立普通股每日收盤價與上櫃發行股數快取。

輸入：archive/raw/twse|tpex/YYYYMMDD.json.gz（證交所 MI_INDEX、櫃買每日收盤行情原始檔）
輸出：cache/wh_px.json.gz  {"dates":[...], "px":{代號:[收盤或null,...]}, "hi"/"lo":{代號:[當日最高／最低價,...]}, "otc_sh":{代號:[發行股數或null,...]}, "mkt":{代號:"twse"|"tpex"}, "name":{代號:名稱}}

普通股：代號為 4 碼數字、不以 0 開頭，排除 91 開頭（存託憑證 TDR）。
收盤價為交易所公布的未還原收盤；無成交當日記 null。
"""
import glob, gzip, json, math, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'archive', 'raw')
OUT = os.path.join(ROOT, 'cache', 'wh_px.json.gz')
COMMON = re.compile(r'^[1-9]\d{3}$')


def num(x):
    try:
        v = float(str(x).replace(',', '').strip())
        return v if v > 0 else None
    except ValueError:
        return None


def is_common(c):
    return bool(COMMON.match(c)) and not c.startswith('91')


def parse(market, path):
    """回傳 {代號: (收盤, 發行股數, 名稱, 最高, 最低, 參考價資訊)}；
    參考價資訊：上市＝(漲跌符號, 漲跌價差)；上櫃＝(次日漲停價, 次日跌停價, 當日漲跌)（次日價供下一交易日使用）"""
    j = json.load(gzip.open(path))
    rows = {}
    for t in j.get('tables') or []:
        f = [x.strip() for x in (t.get('fields') or [])]
        if market == 'twse' and '證券代號' in f:
            ic, iname, ip = f.index('證券代號'), f.index('證券名稱'), f.index('收盤價')
            ih, il = f.index('最高價'), f.index('最低價')
            isg, idf = f.index('漲跌(+/-)'), f.index('漲跌價差')
            for r in t.get('data') or []:
                c = r[ic].strip()
                if is_common(c):
                    sg = re.sub('<[^>]+>', '', r[isg]).strip()
                    rows[c] = (num(r[ip]), None, r[iname].strip(), num(r[ih]), num(r[il]), (sg, num0(r[idf])))
        elif market == 'tpex' and '代號' in f:
            ic, iname, ip = f.index('代號'), f.index('名稱'), f.index('收盤')
            ish = f.index('發行股數') if '發行股數' in f else None
            ih, il = f.index('最高'), f.index('最低')
            ichg = f.index('漲跌')
            iu = f.index('次日漲停價') if '次日漲停價' in f else None
            idn = f.index('次日跌停價') if '次日跌停價' in f else None
            for r in t.get('data') or []:
                c = r[ic].strip()
                if is_common(c):
                    rows[c] = (num(r[ip]), num(r[ish]) if ish is not None else None, r[iname].strip(), num(r[ih]), num(r[il]),
                               (num(r[iu]) if iu is not None else None, num(r[idn]) if idn is not None else None,
                                num0(re.sub(r'\s+', '', r[ichg]))))
    return rows


def num0(x):
    try: return float(str(x).replace(',', '').strip())
    except ValueError: return None


# ---- 上市漲跌停價（依當時制度） ----
TICK_CHANGE = '20050301'   # 升降單位新制生效日（證交所條文對照）


def tick(p, ds):
    if ds < TICK_CHANGE:
        return 0.01 if p < 5 else 0.05 if p < 15 else 0.1 if p < 50 else 0.5 if p < 150 else 1 if p < 1000 else 5
    return 0.01 if p < 10 else 0.05 if p < 50 else 0.1 if p < 100 else 0.5 if p < 500 else 1 if p < 1000 else 5


def limit_pct(ds, up):
    if ds >= '20150601': return 0.10
    if not up and '20081013' <= ds <= '20081024': return 0.035   # 2008/10/13～10/24 跌幅暫縮為 3.5%（央行金融穩定報告 97/12）
    return 0.07


def limits(ref, ds):
    """漲停價向下、跌停價向上取至該價位的升降單位（跨級距時以所在級距重算）"""
    u = ref * (1 + limit_pct(ds, True)); t = tick(u, ds); up = math.floor(u / t + 1e-9) * t
    if tick(up, ds) != t: t = tick(up, ds); up = math.floor(u / t + 1e-9) * t
    d = ref * (1 - limit_pct(ds, False)); t = tick(d, ds); dn = math.ceil(d / t - 1e-9) * t
    if tick(dn, ds) != t: t = tick(dn, ds); dn = math.ceil(d / t - 1e-9) * t
    return round(up, 2), round(dn, 2)


def event_limits():
    """除權息、減資、變更面額恢復買賣日：證交所公告的漲停／跌停價 {(日期, 代號): (漲停, 跌停)}"""
    out = {}
    for fp in glob.glob(os.path.join(RAW, 'twse_events', '*.json')):
        j = json.load(open(fp)); f = [x.strip() for x in j.get('fields') or []]
        if '漲停價格' not in f: continue
        iu, idn = f.index('漲停價格'), f.index('跌停價格')
        for r in j.get('data') or []:
            m = re.match(r'\s*(\d+)\D+(\d+)\D+(\d+)', r[0])
            ds = '%d%02d%02d' % (int(m[1]) + 1911, int(m[2]), int(m[3]))
            out[(ds, r[1].strip())] = (num(r[iu]), num(r[idn]))
    return out


NOLIMIT_START = '20050301'   # 初次上市（櫃）普通股首五個交易日無漲跌幅限制自 2005/03/01 起適用


def initial_listings():
    """初次上市日：證交所「最近上市公司」各年度清單（排除櫃轉市、股份轉換成立控股、創新板）；
    初次上櫃日：櫃買上櫃公司基本資料（僅現存公司）。回傳 ({代號: 上市日}, {代號: 上櫃日})"""
    tw, tp = {}, {}
    d = os.path.join(RAW, 'twse_newlisting')
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        j = json.load(open(os.path.join(d, fn))); f = j['fields']
        for r in j.get('data') or []:
            note = r[f.index('備註')] or ''
            # 排除：櫃轉市、股份轉換成立控股（營業細則第 63 條：上櫃轉上市不適用）；創新板初次上市仍有 10% 限制
            # （官方漲跌停家數與盤中價格皆顯示首五日鎖漲跌停，如 6854、2432、6902）
            if any(k in note for k in ('櫃轉市', '轉換', '轉投控', '轉金控', '下市', '創新板')): continue
            a, b, c = r[f.index('股票上市買賣日期')].split('.')
            tw[r[f.index('公司代號')].strip()] = '%d%s%s' % (int(a) + 1911, b, c)
    d = os.path.join(RAW, 'tpex_companies')
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        for r in json.load(open(os.path.join(d, fn))):
            if r.get('DateOfListing'): tp[r['SecuritiesCompanyCode'].strip()] = r['DateOfListing']
    return tw, tp


def main():
    # 2026-10-28 Ed 要求盡量往前延伸：使用 data/quotes 全部交易日（上市 2004/02 起、上櫃 2007/07 起）
    days = sorted(f[:8] for f in os.listdir(os.path.join(ROOT, 'data', 'quotes')) if f.endswith('.json'))
    px, sh, mkt, name, hi, lo, lim, mk = {}, {}, {}, {}, {}, {}, {}, {}
    evl = event_limits()
    n = len(days)
    # 首五日無漲跌幅：以初次上市（櫃）日起算的前 5 個交易日
    tw_ipo, tp_ipo = initial_listings()
    nolim = set()
    for mkt_, ipo in (('t', tw_ipo), ('o', tp_ipo)):
        for c, d0 in ipo.items():
            if d0 < NOLIMIT_START: continue
            k = next((i for i, x in enumerate(days) if x >= d0), None)
            if k is not None: nolim |= {(mkt_, c, days[j]) for j in range(k, min(k + 5, n))}
    seen_tpex = set()
    nxt = {}   # 上櫃：前一交易日公布的次日漲跌停價
    first_tp = next(i for i, x in enumerate(days) if os.path.exists(os.path.join(RAW, 'tpex', x + '.json.gz')) and parse('tpex', os.path.join(RAW, 'tpex', x + '.json.gz')))
    for i, d in enumerate(days):
        new_nxt = {}
        for m in ('twse', 'tpex'):
            p = os.path.join(RAW, m, d + '.json.gz')
            if not os.path.exists(p):
                print('missing', m, d, file=sys.stderr); continue
            for c, (close, shares, nm, h, l, ri) in parse(m, p).items():
                if c not in px:
                    px[c] = [None] * n; hi[c] = [None] * n; lo[c] = [None] * n; lim[c] = [None] * n; mk[c] = [None] * n
                    if m == 'tpex': sh[c] = [None] * n
                if m == 'tpex' and c not in sh: sh[c] = [None] * n
                px[c][i] = close; mk[c][i] = 'o' if m == 'tpex' else 't'
                if close: hi[c][i] = h or close; lo[c][i] = l or close
                if m == 'tpex': sh[c][i] = shares
                mkt[c] = m; name[c] = nm
                # 漲跌停判定：1＝收漲停、-1＝收跌停、0＝都不是、None＝無法判定（無成交、查無參考價）
                up = dn = None
                if close:
                    if m == 'tpex':
                        up, dn = nxt.get(c, (None, None))
                        # 前一日無公布次日漲跌停價：曾在上櫃交易過（停止買賣後恢復等）才以當日漲跌反推；
                        # 首次出現（初次上櫃、轉市場）不判定。資料首日（2007/07/02）例外
                        if not (up and dn) and ri[2] is not None and close - ri[2] > 0 and (c in seen_tpex or i == first_tp):
                            up, dn = limits(close - ri[2], d)   # 前一日無公布次日漲跌停價（如前一日無交易）：以當日漲跌反推參考價
                    else:
                        sg, df = ri
                        if (d, c) in evl: up, dn = evl[(d, c)]
                        elif sg in ('+', '-', '') and df is not None:
                            ref = close - df if sg == '+' else close + df if sg == '-' else close
                            if ref > 0: up, dn = limits(ref, d)
                if close and (('t' if m == 'twse' else 'o'), c, d) in nolim:
                    up = dn = None   # 初次上市（櫃）首五日無漲跌幅限制：不判定
                if close and up and dn:
                    lim[c][i] = 1 if abs(close - up) < 1e-6 else -1 if abs(close - dn) < 1e-6 else 0
                if m == 'tpex': seen_tpex.add(c)
                if m == 'tpex' and ri[0] and ri[1]: new_nxt[c] = ri[:2]
        nxt = new_nxt
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, 'wt', encoding='utf-8') as fh:
        json.dump({'dates': days, 'px': px, 'hi': hi, 'lo': lo, 'lim': lim, 'mk': mk, 'otc_sh': sh, 'mkt': mkt, 'name': name},
                  fh, ensure_ascii=False, separators=(',', ':'))
    print('days', n, 'codes', len(px), 'otc', len(sh))


if __name__ == '__main__':
    main()
