"""率先創新高 ny_build.build_anchor 的規則測試：凍結門檻、嚴格大於、同日並列、累積比例、未上市排除。"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
import ny_build

ny_build.WIN = 3
ny_build.load_themes = lambda anchor: ({'X': ['1111', '2222', '3333']}, {'X': '電子'})


def run():
    dates = ['d1', 'd2', 'd3', 'd4', 'd5', 'd6']   # 錨點 d3；門檻看 d1～d3
    codes = ['1111', '2222', '3333', '4444']
    n = np.nan
    adjH = np.array([
        [10, 10, n, 10],
        [12, 10, n, 10],
        [9, 10, 5, 10],
        [12, 11, 5, 10],   # 1111 等於門檻不算；2222 突破
        [13, 11, 6, 10],   # 1111 突破；3333 突破（上市未滿門檻窗）
        [5, 11, 6, 10.5],  # 4444 突破；1111 跌回仍算已創高
    ], float)
    adj = adjH.copy(); close = adjH.copy(); pct = np.zeros_like(adjH)
    taiex = dict(zip(dates, [100, 90, 80, 85, 88, 90]))
    a = {'date': 'd3', 'current': True}
    return ny_build.build_anchor(a, dates, codes, adj, adjH, close, pct, taiex, dates, {}, {}, {})


def test_rules():
    r = run()
    got = {x['c']: (x['s'], x['rk'], x['cp']) for x in r['rows']}
    assert r['N'] == 4, r['N']
    assert got == {'2222': ('d4', 1, 25.0), '1111': ('d5', 2, 75.0), '3333': ('d5', 2, 75.0), '4444': ('d6', 4, 100.0)}, got
    assert [d[2] for d in r['days']] == [0, 1, 2, 1]
    assert r['taiex']['hi'] == 100 and r['taiex']['hi_d'] == 'd1'
    assert next(x for x in r['rows'] if x['c'] == '3333')['short'] is True
    t = r['themes'][0]
    assert t['b'] == 3 and t['clu'] is True, t


if __name__ == '__main__':
    test_rules(); print('ok')
