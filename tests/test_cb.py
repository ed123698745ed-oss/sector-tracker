"""可轉債追蹤防錯測試：python3 tests/test_cb.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from cb_common import parse, ParseError
import cb_fetch

H = 'TITLE,x\nDATADATE,日期:115年11月03日\nHEADER,代號,名稱,交易,收市,漲跌,開市,最高,最低,筆數,單位,金額,均價,明日參價,明日漲停,明日跌停\n'
B1 = 'BODY,"12951","生合一","等價","87.95","-5.95","","","","70","307","","","87.95","",""\nBODY,"","","議價","","","","","","","","","","","",""\n'
B2 = 'BODY,"11011","台泥一永","等價","","","","","","","","","","104.50","",""\n'
T = 'BODY,"合計","","","","","","","","70","307","","","","",""\n'

def raw(s): return s.encode('big5')

def test_parse():
    d, rows = parse(raw(H + B1 + B2 + T))
    assert d == '20261103' and len(rows) == 2
    assert rows[0]['close'] == 87.95 and rows[1]['close'] is None and rows[1]['ref'] == 104.5

def test_incomplete_or_html():
    for bad in [H + B1, '<html>', '']:
        try: parse(raw(bad)); assert False
        except ParseError: pass

def test_zero_trade_not_saved():   # 春節前只交割不交易日：有參價、無成交
    _, rows = parse(raw(H + B2 + T))
    assert '非交易日' in cb_fetch.save('20990101', b'', rows)

for k, f in list(globals().items()):
    if k.startswith('test_'): f(); print('ok', k)
