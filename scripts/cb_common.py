"""可轉債追蹤：櫃買中心 RSta0113「轉(交)換公司債買賣斷交易行情表」共用解析。

來源：https://www.tpex.org.tw/storage/bond_zone/tradeinfo/cb/YYYY/YYYYMM/RSta0113.YYYYMMDD-C.csv（Big5）
原始檔備份：archive/raw/tpex_cb/YYYY/YYYYMMDD.csv.gz（原樣 gzip，不改內容）
只供觀察市場，不是交易訊號。
"""
import csv, gzip, io, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH = os.path.join(ROOT, 'archive', 'raw', 'tpex_cb')
URL = 'https://www.tpex.org.tw/storage/bond_zone/tradeinfo/cb/{y}/{y}{m}/RSta0113.{d}-C.csv'


def url(d):
    return URL.format(y=d[:4], m=d[4:6], d=d)


def arch_path(d):
    return os.path.join(ARCH, d[:4], f'{d}.csv.gz')


def archived_dates():
    out = []
    if not os.path.isdir(ARCH):
        return out
    for y in sorted(os.listdir(ARCH)):
        p = os.path.join(ARCH, y)
        if os.path.isdir(p):
            out += [f[:8] for f in os.listdir(p) if re.fullmatch(r'\d{8}\.csv\.gz', f)]
    return sorted(out)


def closed_dates():
    p = os.path.join(ROOT, 'data', 'closed.txt')
    if not os.path.exists(p):
        return set()
    return {l.strip()[:8] for l in open(p, encoding='utf-8') if re.match(r'\d{8}', l.strip())}


def _num(x):
    x = (x or '').strip().replace(',', '')
    try:
        return float(x)
    except ValueError:
        return None


class ParseError(Exception):
    pass


def parse(raw):
    """回傳 (資料日 YYYYMMDD, rows)。rows：每檔一筆 dict（只取「等價」列；議價列不用）。

    檢查：TITLE 開頭、DATADATE 可解析、有 HEADER、有「合計」列（檔案完整）。不符即丟 ParseError。
    """
    if raw[:5] != b'TITLE':
        raise ParseError('檔頭不是 TITLE（可能是 HTML 或空檔）')
    txt = raw.decode('big5', errors='replace')
    date = hdr = None
    rows, has_total = [], False
    for rec in csv.reader(io.StringIO(txt)):
        if not rec:
            continue
        tag = rec[0]
        if tag == 'DATADATE':
            m = re.search(r'(\d{2,3})年(\d{1,2})月(\d{1,2})日', ''.join(rec[1:]))
            if m:
                date = f'{int(m.group(1)) + 1911:04d}{int(m.group(2)):02d}{int(m.group(3)):02d}'
        elif tag == 'HEADER':
            hdr = [c.strip() for c in rec[1:]]
        elif tag == 'BODY' and hdr:
            r = dict(zip(hdr, [c.strip() for c in rec[1:]]))
            code = r.get('代號', '')
            if code == '合計':
                has_total = True
                continue
            if not re.fullmatch(r'\d{4,6}', code) or r.get('交易') != '等價':
                continue
            rows.append({'code': code, 'name': r.get('名稱', '').strip(),
                         'close': _num(r.get('收市')), 'chg': _num(r.get('漲跌')),
                         'ref': _num(r.get('明日參價')), 'units': _num(r.get('單位')),
                         'trades': _num(r.get('筆數'))})
    if not date:
        raise ParseError('讀不到 DATADATE')
    if not hdr:
        raise ParseError('讀不到 HEADER')
    if not has_total:
        raise ParseError('沒有「合計」列，檔案可能不完整')
    return date, rows


def load(d):
    with gzip.open(arch_path(d), 'rb') as f:
        return parse(f.read())
