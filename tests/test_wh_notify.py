"""推播決策：就緒、去重、重試、dry-run。不打 LINE。"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import wh_notify  # noqa: E402


TH = {'down': [0.09, 0.06], 'up': [0.2, 0.05]}


def fixture(states, date='20261029', down=None):
    n = len(states)
    # 兩天就夠；日期用同一月的假交易日，最後一天＝stock_date。
    dates = ['20261028', date][:n]
    if n == 1:
        dates = [date]
    while len(dates) < n:
        dates.insert(0, f'202610{20+len(dates):02d}')
    if down is None:
        down = [-0.05] * n
    return {
        'stock_date': dates[-1],
        'dates': dates,
        'taiex': [20000 + i for i in range(n)],
        'ext': {
            'state': states,
            'dd': down,
            'ru': [0.04] * n,
            'conc': [0.3] * n,
            'th': TH,
        },
    }


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, 'docs'))
        os.makedirs(os.path.join(self.root, 'data', 'quotes'))
        self._env = {
            k: os.environ.get(k) for k in ('LINE_CHANNEL_ACCESS_TOKEN', 'LINE_USER_ID')
        }
        os.environ.pop('LINE_CHANNEL_ACCESS_TOKEN', None)
        os.environ.pop('LINE_USER_ID', None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def write(self, w, quote=True):
        json.dump(w, open(os.path.join(self.root, 'docs', 'wh.json'), 'w', encoding='utf-8'))
        if quote:
            open(os.path.join(self.root, 'data', 'quotes', w['stock_date'] + '.json'), 'w').write('{}')

    def test_preview_is_labeled_and_not_sent(self):
        ev = wh_notify.run(self.root, preview_test=True)
        self.assertTrue(ev['message'].startswith('【測試】'))
        self.assertIn('只供觀察，不是交易訊號', ev['message'])
        self.assertEqual(ev['action'], 'not_sent')
        self.assertFalse(os.path.exists(wh_notify.ledger_path(self.root)))

    def test_unchanged_noop(self):
        self.write(fixture([0, 0]))
        ev = wh_notify.run(self.root, sleep_s=0)
        self.assertEqual(ev['action'], 'noop')
        self.assertEqual(ev['reason'], 'state_unchanged')

    def test_dry_run_does_not_send_or_record(self):
        self.write(fixture([0, -1]))
        calls = []
        os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = 'SUPERSECRETTOKEN'
        os.environ['LINE_USER_ID'] = 'Usecretuser'
        ev = wh_notify.run(self.root, dry_run=True, sleep_s=0, push_fn=lambda m: calls.append(m) or 200)
        self.assertEqual(ev['action'], 'would_send')
        self.assertEqual(calls, [])
        self.assertNotIn('SUPERSECRETTOKEN', json.dumps(ev))
        self.assertNotIn('Usecretuser', json.dumps(ev))
        self.assertNotIn('測試', ev['message'])
        self.assertIn('只供觀察，不是交易訊號', ev['message'])
        self.assertFalse(os.path.exists(wh_notify.ledger_path(self.root)))

    def test_dedup_same_transition(self):
        self.write(fixture([0, -1]))
        os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = 'tok'
        os.environ['LINE_USER_ID'] = 'uid'
        calls = []
        ev1 = wh_notify.run(self.root, sleep_s=0, push_fn=lambda m: calls.append(m) or 200)
        ev2 = wh_notify.run(self.root, sleep_s=0, push_fn=lambda m: calls.append(m) or 200)
        self.assertEqual(ev1['action'], 'sent')
        self.assertEqual(ev1['recipient'], 'configured')
        self.assertEqual(ev2['action'], 'dedup')
        self.assertEqual(len(calls), 1)
        led = json.load(open(wh_notify.ledger_path(self.root), encoding='utf-8'))
        self.assertNotIn('tok', json.dumps(led))
        self.assertNotIn('uid', json.dumps(led))

    def test_retry_then_retry_only(self):
        self.write(fixture([0, 1]))
        os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = 'tok'
        os.environ['LINE_USER_ID'] = 'uid'
        calls = {'n': 0}

        def fail(_m):
            calls['n'] += 1
            return False

        ev = wh_notify.run(self.root, sleep_s=0, attempts=3, push_fn=fail)
        self.assertEqual(ev['action'], 'failed')
        self.assertEqual(calls['n'], 3)
        calls['n'] = 0
        ev2 = wh_notify.run(self.root, retry_only=True, sleep_s=0, attempts=1, push_fn=lambda m: calls.__setitem__('n', calls['n'] + 1) or 200)
        self.assertEqual(ev2['action'], 'sent')
        self.assertEqual(calls['n'], 1)
        ev3 = wh_notify.run(self.root, retry_only=True, sleep_s=0, push_fn=lambda m: calls.__setitem__('n', calls['n'] + 1) or 200)
        self.assertEqual(ev3['action'], 'dedup')

    def test_retry_only_without_failed_record_does_not_send(self):
        self.write(fixture([0, -1]))
        os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = 'tok'
        os.environ['LINE_USER_ID'] = 'uid'
        calls = []
        ev = wh_notify.run(self.root, retry_only=True, sleep_s=0, push_fn=lambda m: calls.append(1) or 200)
        self.assertEqual(ev['action'], 'skip')
        self.assertEqual(calls, [])

    def test_no_secrets_not_marked_sent(self):
        self.write(fixture([0, 1]))
        ev = wh_notify.run(self.root, sleep_s=0, push_fn=lambda m: 200)
        self.assertEqual(ev['action'], 'skipped_no_secrets')
        self.assertEqual(ev['recipient'], 'unset')
        self.assertFalse(os.path.exists(wh_notify.ledger_path(self.root)))

    def test_not_ready_expect_date_and_missing_quote(self):
        w = fixture([0, -1], date='20261029')
        self.write(w, quote=False)
        ev = wh_notify.run(self.root, expect_date='2026-10-29', sleep_s=0)
        self.assertEqual(ev['action'], 'not_ready')
        self.assertIn('quote_file_missing', ev['reasons'])
        self.write(w, quote=True)
        ev2 = wh_notify.run(self.root, expect_date='20261028', sleep_s=0)
        self.assertIn('expect_date_mismatch', ev2['reasons'])

    def test_abnormal_without_score_and_threshold_mismatch(self):
        w = fixture([0, -1], down=[-0.05, None])
        self.write(w)
        ev = wh_notify.run(self.root, sleep_s=0)
        self.assertIn('abnormal_score_missing', ev['reasons'])
        w = fixture([0, -1])
        w['ext']['th'] = {'down': [0.1, 0.06], 'up': [0.2, 0.05]}
        self.write(w)
        ev2 = wh_notify.run(self.root, sleep_s=0)
        self.assertIn('threshold_mismatch', ev2['reasons'])

    def test_push_error_redacts_secret(self):
        self.write(fixture([-1, 0]))
        os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = 'SUPERSECRETTOKEN'
        os.environ['LINE_USER_ID'] = 'Usecretuser'

        def blow(_m):
            raise RuntimeError('failed SUPERSECRETTOKEN for Usecretuser')

        ev = wh_notify.run(self.root, sleep_s=0, attempts=1, push_fn=blow)
        led = json.load(open(wh_notify.ledger_path(self.root), encoding='utf-8'))
        blob = json.dumps({'ev': ev, 'led': led}, ensure_ascii=False)
        self.assertNotIn('SUPERSECRETTOKEN', blob)
        self.assertNotIn('Usecretuser', blob)
        self.assertIn('[redacted]', blob)
        self.assertEqual(ev['action'], 'failed')


if __name__ == '__main__':
    unittest.main()
