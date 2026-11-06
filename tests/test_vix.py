"""臺指 VIX 解析測試：python3 tests/test_vix.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
import vix  # noqa: E402

SAMPLE = ('交易日期\t時間(時/分/秒/毫秒)\t臺指選擇權波動率指數\t收盤前1分鐘平均指數\n'
          '--------\t-------------------\t--------------------\t-------------------\n'
          '20261022\t13450000\t\t\t30.31\t\t30.35\n20261027\t13450000\t\t\t29.86\t\t29.86\n')

def t_parse():
    for enc in ('utf-8', 'big5'):
        r = vix.parse_month(SAMPLE.encode(enc))
        assert r == {'20261022': (30.31, 30.35), '20261027': (29.86, 29.86)}, r
    # 颱風休市 10/23、補假 10/26 不在檔內 → 不產生資料列（日期以檔案為準）
    assert '20261023' not in r

def t_bad():
    for raw in (b'', b'<html>error</html>', '臺指選擇權波動率指數\n20261022 13450000 abc'.encode()):
        try:
            vix.parse_month(raw); raise AssertionError('應失敗')
        except ValueError:
            pass

def t_months():
    import datetime
    assert vix.months_back(4, datetime.datetime(2026, 1, 15)) == ['202601', '202512', '202511', '202510']

if __name__ == '__main__':
    t_parse(); t_bad(); t_months(); print('test_vix ok')
