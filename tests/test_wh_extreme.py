"""市場狀態計算與狀態機。不送推播、不改資料檔。"""
import copy
import json
import os
import sys
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import wh_extreme  # noqa: E402


def days(n, start='20050103'):
    d = datetime.strptime(start, '%Y%m%d')
    out = []
    for _ in range(n):
        out.append(d.strftime('%Y%m%d'))
        d += timedelta(days=1)
    return out


def inputs(n, start='20050103', price=100.0):
    dates = days(n, start)
    taiex = [price + i * 0.2 for i in range(n)]
    allg = {
        'n': [100] * n,
        'ld': [4] * n,
        'lu': [1] * n,
        'dd': [[40, 15, 15, 10, 10, 10] for _ in range(n)],
    }
    turnover = [100.0] * n
    conc = [0.2] * n
    return dates, taiex, allg, turnover, conc


class BoundaryTests(unittest.TestCase):
    def test_all_cases_match_expected(self):
        table = wh_extreme.boundary_rows()
        bad = [r for r in table['rows'] if not r['match']]
        self.assertEqual(bad, [])
        groups = {r['group'] for r in table['rows']}
        for name in ('恰等於進入', '同時達標', '既有狀態維持與競合', '退出與切換', '暖機不足與缺值'):
            self.assertIn(name, groups)

    def test_thresholds_enter_above_exit(self):
        for key, (enter, exit_) in wh_extreme.TH.items():
            self.assertGreater(enter, exit_, key)


class PointInTimeTests(unittest.TestCase):
    def test_warmup_before_minhist_is_normal(self):
        dates, taiex, allg, turnover, conc = inputs(40)
        ext = wh_extreme.compute(dates, taiex, allg, turnover, conc)
        self.assertTrue(all(v is None for v in ext['down']))
        self.assertTrue(all(v is None for v in ext['up']))
        self.assertTrue(all(v is None for v in ext['conc']))
        self.assertTrue(all(s == 0 for s in ext['state']))

    def test_dates_before_start_are_excluded(self):
        dates, taiex, allg, turnover, conc = inputs(300, start='20040101')
        self.assertLess(dates[-1], wh_extreme.START)
        ext = wh_extreme.compute(dates, taiex, allg, turnover, conc)
        self.assertTrue(all(v is None for v in ext['down']))
        self.assertTrue(all(s == 0 for s in ext['state']))

    def test_every_prefix_matches_full_series(self):
        dates, taiex, allg, turnover, conc = inputs(80)
        full = wh_extreme.compute(dates, taiex, allg, turnover, conc, minh=10)
        for i in range(len(dates)):
            sub_allg = {k: allg[k][:i + 1] for k in allg}
            got = wh_extreme.compute(dates[:i + 1], taiex[:i + 1], sub_allg, turnover[:i + 1], conc[:i + 1], minh=10)
            self.assertEqual(got['state'][-1], full['state'][i], dates[i])
            self.assertEqual(got['down'][-1], full['down'][i], dates[i])
            self.assertEqual(got['up'][-1], full['up'][i], dates[i])
            self.assertEqual(got['conc'][-1], full['conc'][i], dates[i])

    def test_future_input_does_not_change_past(self):
        dates, taiex, allg, turnover, conc = inputs(80)
        full = wh_extreme.compute(dates, taiex, allg, turnover, conc, minh=10)
        taiex2 = taiex[:]
        taiex2[-1] = 1
        turnover2 = turnover[:]
        turnover2[-1] = 99999
        conc2 = conc[:]
        conc2[-1] = 0.95
        allg2 = copy.deepcopy(allg)
        allg2['ld'][-1] = 80
        allg2['dd'][-1] = [0, 0, 0, 0, 0, 100]
        full2 = wh_extreme.compute(dates, taiex2, allg2, turnover2, conc2, minh=10)
        for key in ('state', 'down', 'up', 'conc'):
            self.assertEqual(full2[key][:-1], full[key][:-1])


class SnapshotTests(unittest.TestCase):
    def test_review_snapshot_counts_when_present(self):
        path = os.path.join(ROOT, 'docs', 'wh.json')
        if not os.path.exists(path):
            self.skipTest('no wh.json')
        w = json.load(open(path, encoding='utf-8'))
        if w.get('stock_date') != '20261029':
            self.skipTest('snapshot moved past review date')
        ext = w['ext']
        scored = sum(v is not None for v in ext['down'])
        abnormal = sum(s != 0 for s in ext['state'])
        self.assertEqual(scored, 5093)
        self.assertEqual(abnormal, 695)
        self.assertEqual(ext['state'][-1], 0)
        self.assertEqual(ext['down'][-1], 0.694)
        self.assertEqual(ext['up'][-1], 0.394)
        self.assertEqual(ext['conc'][-1], 0.595)
        for key, (a, b) in wh_extreme.TH.items():
            self.assertEqual(float(ext['th'][key][0]), a)
            self.assertEqual(float(ext['th'][key][1]), b)


if __name__ == '__main__':
    unittest.main()
