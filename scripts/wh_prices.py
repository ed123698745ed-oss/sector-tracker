"""權值與高價股觀察分頁：從原始收盤行情建立普通股每日收盤價與上櫃發行股數快取。

輸入：archive/raw/twse|tpex/YYYYMMDD.json.gz（證交所 MI_INDEX、櫃買每日收盤行情原始檔）
輸出：cache/wh_px.json.gz  {"dates":[...], "px":{代號:[收盤或null,...]}, "otc_sh":{代號:[發行股數或null,...]}, "mkt":{代號:"twse"|"tpex"}, "name":{代號:名稱}}

普通股：代號為 4 碼數字、不以 0 開頭，排除 91 開頭（存託憑證 TDR）。
收盤價為交易所公布的未還原收盤；無成交當日記 null。
"""
import gzip, json, os, re, sys

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
    j = json.load(gzip.open(path))
    rows = {}
    for t in j.get('tables') or []:
        f = [x.strip() for x in (t.get('fields') or [])]
        if market == 'twse' and '證券代號' in f:
            ic, iname, ip = f.index('證券代號'), f.index('證券名稱'), f.index('收盤價')
            for r in t.get('data') or []:
                c = r[ic].strip()
                if is_common(c):
                    rows[c] = (num(r[ip]), None, r[iname].strip())
        elif market == 'tpex' and '代號' in f:
            ic, iname, ip = f.index('代號'), f.index('名稱'), f.index('收盤')
            ish = f.index('發行股數') if '發行股數' in f else None
            for r in t.get('data') or []:
                c = r[ic].strip()
                if is_common(c):
                    rows[c] = (num(r[ip]), num(r[ish]) if ish is not None else None, r[iname].strip())
    return rows


def main():
    # 權值高價股分頁歷史自 2015 年起（上市股數財報自 2014Q3 起可用）；data/quotes 另有更早資料供其他研究使用
    days = sorted(f[:8] for f in os.listdir(os.path.join(ROOT, 'data', 'quotes')) if f.endswith('.json') and f[:8] >= '20150101')
    px, sh, mkt, name = {}, {}, {}, {}
    n = len(days)
    for i, d in enumerate(days):
        for m in ('twse', 'tpex'):
            p = os.path.join(RAW, m, d + '.json.gz')
            if not os.path.exists(p):
                print('missing', m, d, file=sys.stderr); continue
            for c, (close, shares, nm) in parse(m, p).items():
                if c not in px:
                    px[c] = [None] * n
                    if m == 'tpex': sh[c] = [None] * n
                if m == 'tpex' and c not in sh: sh[c] = [None] * n
                px[c][i] = close
                if m == 'tpex': sh[c][i] = shares
                mkt[c] = m; name[c] = nm
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, 'wt', encoding='utf-8') as fh:
        json.dump({'dates': days, 'px': px, 'otc_sh': sh, 'mkt': mkt, 'name': name}, fh, ensure_ascii=False, separators=(',', ':'))
    print('days', n, 'codes', len(px), 'otc', len(sh))


if __name__ == '__main__':
    main()
