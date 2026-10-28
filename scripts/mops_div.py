"""解析公開資訊觀測站「股利分派情形」(t05st09) 個別公司原始檔。
回傳 [(每股現金股利, 每股配股(元), 面額), ...]，每筆為一次股利決議（同年度可能多次）。
舊版頁面（約 2012 年以前）：現金＝現金股利，配股＝盈餘配股＋資本公積轉增資。
新版：現金＝盈餘分配之現金股利＋法定盈餘公積、資本公積發放之現金；配股＝盈餘轉增資配股＋法定盈餘公積、資本公積轉增資配股。
"""
import gzip, re
from html.parser import HTMLParser


class _P(HTMLParser):
    def __init__(s):
        super().__init__(); s.rows = []; s.row = None; s.cell = None
    def handle_starttag(s, tag, a):
        if tag == 'tr': s.row = []
        elif tag in ('td', 'th'): s.cell = ''
    def handle_endtag(s, tag):
        if tag in ('td', 'th') and s.row is not None and s.cell is not None:
            s.row.append(re.sub(r'\s+', '', s.cell.replace('\xa0', ''))); s.cell = None
        elif tag == 'tr' and s.row is not None:
            s.rows.append(s.row); s.row = None
    def handle_data(s, d):
        if s.cell is not None: s.cell += d


def _f(x):
    try: return float(x.replace(',', ''))
    except (ValueError, AttributeError): return None


def parse_div(path):
    p = _P(); p.feed(gzip.open(path, 'rt', encoding='utf-8', errors='replace').read())
    txt = ' '.join(' '.join(r) for r in p.rows)
    m = re.search(r'新台幣\s*([\d.]+)\s*元', txt)
    par = float(m[1]) if m else 10.0
    out = []
    # 舊版頁面（約 2012 年以前）欄位：年度、股東會日期、期別、現金股利、盈餘配股、資本公積轉增資、董監酬勞…
    old = '盈餘分配之現金股利' not in txt and '盈餘配股' in txt
    for r in p.rows:
        # 資料列：第 1 欄為股利所屬年度（3 碼數字），第 2 欄為股東會日期 yyy/mm/dd
        if len(r) >= 12 and re.fullmatch(r'\d{2,3}', r[0] or '') and re.fullmatch(r'\d{2,3}/\d{2}/\d{2}', r[1] or ''):
            nums = [_f(x) for x in r]
            if old:
                out.append(((nums[3] or 0), (nums[4] or 0) + (nums[5] or 0), par)); continue
            # 欄位順序（t05st09）：年度、股東會日期、期別、可分配盈餘、本期淨利、累積未分配盈餘、
            # 現金股利總額、盈餘分配之現金股利(元/股)、公積發放之現金(元/股)、現金股利總金額、
            # 盈餘轉增資配股(元/股)、公積轉增資配股(元/股)、配股總股數
            cash = (nums[7] or 0) + (nums[8] or 0)
            stock = (nums[10] or 0) + (nums[11] or 0)
            out.append((cash, stock, par))
    return out
