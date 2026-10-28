"""解析「決定分派股息及紅利或其他利益之基準日公告」(t108sb22) 原始檔。
回傳 dict：exdate(除權/除息交易日 YYYYMMDD 或 None)、stock(每股配發股票元)、cash(每股配發現金元)、par、title。
"""
import gzip, re


def _s(path):
    t = gzip.open(path, 'rt', encoding='utf-8', errors='replace').read()
    return re.sub(r'(\| ?)+', '|', re.sub(r'\s+', ' ', re.sub('<[^>]+>', '|', t)))


def _num(pat, s):
    m = re.search(pat, s)
    return float(m[1].replace(',', '')) if m else None


def parse_notice(path):
    s = _s(path)
    r = {}
    r['stock'] = _num(r'除權--普通股：每壹股配發股票\(股利\)\|?\s*([\d.,]+)', s) or 0.0
    r['cash'] = _num(r'除息--普通股：每壹股配發現金\(股利\)\|?\s*([\d.,]+)', s) or 0.0
    p = _num(r'每股面額：\|?\s*新台幣\s*([\d.]+)元', s)
    r['par'] = p or 10.0
    m = re.search(r'除權/除息交易日：\|?\s*(\d+)年(\d+)月(\d+)日', s)
    r['exdate'] = '%d%02d%02d' % (int(m[1]) + 1911, int(m[2]), int(m[3])) if m else None
    m = re.search(r'二、主旨：\|([^|]+)', s)
    r['title'] = m[1].strip() if m else ''
    return r
