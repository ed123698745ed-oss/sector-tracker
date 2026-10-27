"""解析公開資訊觀測站「資產負債表彙總報表」(t163sb05) 原始檔，輸出各季上市公司股本(千元)。
用法：python3 mops_bs.py <raw_dir> <out.json>   輸出 {"YYYQQ": {代號: 股本千元}}
"""
import gzip, json, os, re, sys
from html.parser import HTMLParser


class P(HTMLParser):
    def __init__(s):
        super().__init__(); s.tables = []; s.row = None; s.cell = None
    def handle_starttag(s, tag, a):
        if tag == 'table': s.tables.append([])
        elif tag == 'tr': s.row = []
        elif tag in ('td', 'th'): s.cell = ''
    def handle_endtag(s, tag):
        if tag in ('td', 'th') and s.row is not None and s.cell is not None:
            s.row.append(s.cell.strip()); s.cell = None
        elif tag == 'tr' and s.row is not None:
            if s.tables: s.tables[-1].append(s.row)
            s.row = None
    def handle_data(s, d):
        if s.cell is not None: s.cell += d


def parse(path):
    p = P(); p.feed(gzip.open(path, 'rt', encoding='utf-8', errors='replace').read())
    out = {}
    for tb in p.tables:
        if len(tb) < 2 or '公司代號' not in tb[0]: continue
        h = tb[0]; ic = h.index('公司代號')
        if '股本' not in h: continue
        ik = h.index('股本')
        for r in tb[1:]:
            if len(r) <= ik or r[ic] == '公司代號': continue
            v = r[ik].replace(',', '')
            try: out[r[ic].strip()] = float(v)
            except ValueError: pass
    return out


if __name__ == '__main__':
    raw, dst = sys.argv[1], sys.argv[2]
    res = {}
    for f in sorted(os.listdir(raw)):
        m = re.match(r'sii_(\d{3})_(\d{2})\.html\.gz', f)
        if m: res[m[1] + m[2]] = parse(os.path.join(raw, f))
    json.dump(res, open(dst, 'w'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    for k, v in res.items(): print(k, len(v))
