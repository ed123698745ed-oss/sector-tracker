"""上市公司每月可用普通股股數（財報股本推算），供上市權值前 50 名單使用。

來源：公開資訊觀測站「資產負債表彙總報表」各季原始檔 archive/raw/mops_bs/sii_YYY_QQ.html.gz。
股數＝股本÷面額。面額不直接取現值（曾有面額變更），而是在 10、5、2.5、2、1、0.5、0.25、0.1 元中，
選使「股本÷面額」最接近「母公司權益÷每股參考淨值」的面額。
財報「股本」含特別股，未扣除（少數公司市值略為高估，已於規則註明）。

時點：月底排名只用當時已過申報期限的最新一季：Q1→5 月底起、Q2→8 月底起、Q3→11 月底起、
年報→次年 3 月底起（一般業與金控期限都在該月內）。
當時可用季別查無該公司（例：剛上市）時，改用其後最早一季並標記 late，不推估。
輸出：cache/wh_twse_shares.json {YYYYMM: {代號: 股數}}、cache/wh_twse_shares_note.json（late 與面額紀錄）
"""
import gzip, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from mops_bs import P  # noqa: E402

PARS = [10, 5, 2.5, 2, 1, 0.5, 0.25, 0.1]


def numv(x):
    try:
        return float(str(x).replace(',', ''))
    except (TypeError, ValueError):
        return None


def parse_q(path):
    p = P(); p.feed(gzip.open(path, 'rt', encoding='utf-8', errors='replace').read())
    out = {}
    for tb in p.tables:
        if len(tb) < 2 or '公司代號' not in tb[0] or '股本' not in tb[0]:
            continue
        h = tb[0]
        ieq = next((i for i, x in enumerate(h) if x.startswith('歸屬於母公司業主') and '權益' in x), None)
        inav = h.index('每股參考淨值') if '每股參考淨值' in h else None
        for r in tb[1:]:
            if len(r) < len(h) or r[0] == '公司代號':
                continue
            cap = numv(r[h.index('股本')])
            if not cap:
                continue
            eq = numv(r[ieq]) if ieq is not None else None
            nav = numv(r[inav]) if inav is not None else None
            ref = eq * 1000 / nav if eq and nav and nav > 0 else None
            if ref:
                par = min(PARS, key=lambda p: abs(cap * 1000 / p - ref) / ref)
            else:
                par = 10
            out[r[0].strip()] = (round(cap * 1000 / par), par)
    return out


def parse_sig(path):
    import hashlib
    return hashlib.md5(gzip.open(path).read()).hexdigest()


def avail_quarter(ym):
    """月底可用的最新季別 (民國年, 季)"""
    y, m = int(ym[:4]), int(ym[4:])
    if m >= 11: return y - 1911, 3
    if m >= 8: return y - 1911, 2
    if m >= 5: return y - 1911, 1
    if m >= 3: return y - 1912, 4
    return y - 1912, 3


def main():
    raw = os.path.join(ROOT, 'archive', 'raw', 'mops_bs')
    qs = {}
    for f in sorted(os.listdir(raw)):
        m = re.match(r'sii_(\d{3})_(\d{2})\.html\.gz$', f)
        if m:
            qs[(int(m[1]), int(m[2]))] = parse_q(os.path.join(raw, f))
    keys = sorted(qs)
    # 防錯：觀測站偶爾回傳別季內容（曾發生 114Q4、115Q2 拿到別季），各季原始檔內容不得重複
    sig = {}
    for k in keys:
        eqsig = parse_sig(os.path.join(raw, 'sii_%03d_%02d.html.gz' % k))
        if eqsig in sig:
            sys.exit('季報內容重複：%s 與 %s，請重抓' % (k, sig[eqsig]))
        sig[eqsig] = k
    dates = json.load(gzip.open(os.path.join(ROOT, 'cache', 'wh_px.json.gz'), 'rt', encoding='utf-8'))['dates']
    months = sorted({d[:6] for d in dates})
    out, note = {}, {'missing_quarter': [], 'late': {}, 'par_not_10': {}}
    for ym in months:
        q = avail_quarter(ym)
        if q not in qs:
            note['missing_quarter'].append(ym); continue
        rec = {c: v[0] for c, v in qs[q].items()}
        # 該季彙總表缺該公司：先用前一季（不偷看未來），再缺（剛上市）才用其後最早一季並標記
        prev = [k for k in keys if k < q][-1:]
        for k in prev:
            for c, v in qs[k].items():
                rec.setdefault(c, v[0])
        for k in [k for k in keys if k > q]:
            for c, v in qs[k].items():
                if c not in rec:
                    rec[c] = v[0]; note['late'].setdefault(ym, []).append(c)
        out[ym] = rec
    for k in keys:
        for c, (_, par) in qs[k].items():
            if par != 10:
                note['par_not_10'].setdefault(c, {})['%d Q%d' % k] = par
    json.dump(out, open(os.path.join(ROOT, 'cache', 'wh_twse_shares.json'), 'w'), separators=(',', ':'))
    json.dump(note, open(os.path.join(ROOT, 'cache', 'wh_twse_shares_note.json'), 'w'), ensure_ascii=False, indent=1)
    print('quarters', len(keys), 'months', len(out), 'missing', note['missing_quarter'])


if __name__ == '__main__':
    main()
