"""市場狀態推播：可重跑的 dry-run 證據。不連網、不打 LINE、不讀真的 secrets。

用 mock push 取代 notify.push，在暫存目錄裡模擬每日排程（daily.yml）的分支：
  當日行情檔已在「已提交」狀態 → 只跑 --retry-only，再提交 ledger；
  否則 → 抓取、正式送、（新流程）先單獨提交 ledger、再提交整包資料。
每次排程開始都依「已提交」狀態重建工作目錄，等同乾淨 checkout。git 提交成功與否由情境指定。

  python3 scripts/wh_notify_evidence.py            # 寫 docs/wh-market-state-evidence/notify.json、notify.md
  python3 scripts/wh_notify_evidence.py --check    # 只跑、比對預期，不寫檔

另含一列「實際資料 dry-run」：對 repo 現有 docs/wh.json 跑 wh_notify.run(dry_run=True)，不送、不寫 ledger。
收件者只出現 configured／unset；mock 的 token、user id 若出現在任何輸出即判失敗。
"""
import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wh_extreme  # noqa: E402
import wh_notify  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'wh-market-state-evidence')
MOCK_TOKEN = 'MOCK-TOKEN-not-a-secret'
MOCK_USER = 'MOCK-USER-not-a-secret'
DAY = '20261029'
TH = {k: list(v) for k, v in wh_extreme.TH.items()}


def fixture(states, date=DAY, down=None, th=None):
    n = len(states)
    dates = [f'2026{10:02d}{20 + i:02d}' for i in range(n - 1)] + [date]
    return {
        'stock_date': date,
        'dates': dates,
        'taiex': [20000.0 + i for i in range(n)],
        'ext': {
            'state': list(states),
            'down': list(down) if down is not None else [0.5] * n,
            'up': [0.4] * n,
            'conc': [0.3] * n,
            'th': th or TH,
        },
    }


class MockPush:
    """依序回傳指定結果。True/200 成功，False 失敗，Exception 物件則拋出。"""

    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.calls = []

    def __call__(self, msg):
        self.calls.append(msg)
        r = self.outcomes.pop(0) if self.outcomes else 200
        if isinstance(r, Exception):
            raise r
        return r


class Clock:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f'2026-10-29T14:{self.n:02d}:00+08:00'


@contextmanager
def env(secrets=True):
    keep = {k: os.environ.get(k) for k in ('LINE_CHANNEL_ACCESS_TOKEN', 'LINE_USER_ID')}
    os.environ.pop('LINE_CHANNEL_ACCESS_TOKEN', None)
    os.environ.pop('LINE_USER_ID', None)
    if secrets:
        os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = MOCK_TOKEN
        os.environ['LINE_USER_ID'] = MOCK_USER
    old_now = wh_notify._now
    wh_notify._now = Clock()
    try:
        yield
    finally:
        wh_notify._now = old_now
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class Repo:
    """暫存 repo。committed 是遠端已有的檔案狀態；每次排程從它重建工作目錄。"""

    def __init__(self, w, quote_committed=False):
        self.tmp = tempfile.mkdtemp(prefix='wh_notify_ev_')
        self.w = w
        self.committed = {'ledger': None, 'quote': quote_committed}

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def ledger(self):
        return wh_notify.ledger_path(self.tmp)

    @property
    def quote(self):
        return os.path.join(self.tmp, 'data', 'quotes', self.w['stock_date'] + '.json')

    def checkout(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.makedirs(os.path.join(self.tmp, 'docs'))
        os.makedirs(os.path.join(self.tmp, 'data', 'quotes'))
        with open(os.path.join(self.tmp, 'docs', 'wh.json'), 'w', encoding='utf-8') as f:
            json.dump(self.w, f)
        if self.committed['quote']:
            open(self.quote, 'w').write('{}')
        if self.committed['ledger'] is not None:
            wh_notify.save_ledger(self.ledger, copy.deepcopy(self.committed['ledger']))

    def working_ledger(self):
        return wh_notify.load_ledger(self.ledger) if os.path.exists(self.ledger) else None

    def commit(self, paths, ok):
        """模擬 git commit + push。ok=False 時遠端不變（push 5 次都失敗）。"""
        if not ok:
            return 'push_failed'
        changed = False
        if 'ledger' in paths:
            cur = self.working_ledger()
            if cur != self.committed['ledger']:
                self.committed['ledger'] = copy.deepcopy(cur)
                changed = True
        if 'quote' in paths and os.path.exists(self.quote) and not self.committed['quote']:
            self.committed['quote'] = True
            changed = True
        return 'pushed' if changed else 'nothing_to_commit'


def scheduled_run(repo, push, flow='new', ledger_commit_ok=True, data_commit_ok=True):
    """一次 daily.yml 排程。回傳本次步驟紀錄。"""
    repo.checkout()
    steps = []
    if repo.committed['quote']:
        ev = wh_notify.run(repo.tmp, retry_only=True, expect_date=repo.w['stock_date'],
                           push_fn=push, sleep_s=0)
        steps.append({'step': 'wh_notify --retry-only', 'action': ev['action'], 'reason': ev.get('reason') or ev.get('failure')})
        steps.append({'step': '提交推播重試紀錄', 'git': repo.commit({'ledger'}, ledger_commit_ok)})
        return steps, ev
    open(repo.quote, 'w').write('{}')  # 抓取收盤行情
    steps.append({'step': '抓取收盤行情', 'git': None})
    ev = wh_notify.run(repo.tmp, expect_date=repo.w['stock_date'], push_fn=push, sleep_s=0)
    steps.append({'step': 'wh_notify', 'action': ev['action'], 'reason': ev.get('reason') or ev.get('failure')})
    if flow == 'new':
        steps.append({'step': '提交推播紀錄（單獨、先於資料）', 'git': repo.commit({'ledger'}, ledger_commit_ok)})
    steps.append({'step': '提交更新（含 data/ 與 ledger）', 'git': repo.commit({'ledger', 'quote'}, data_commit_ok)})
    return steps, ev


def _ledger_summary(led):
    if led is None:
        return None
    return [{'stock_date': r['stock_date'], 'from': r['from'], 'to': r['to'], 'result': r['result'],
             'attempts': r['attempts'], 'recipient': r['recipient'], 'at': r['at']} for r in led['records']]


def _single(name, title, w, expect, secrets=True, quote=True, push_outcomes=None, **kw):
    """單次 wh_notify.run，直接在暫存目錄。"""
    repo = Repo(w, quote_committed=quote)
    push = MockPush(push_outcomes)
    try:
        with env(secrets):
            repo.checkout()
            ev = wh_notify.run(repo.tmp, push_fn=push, sleep_s=0, **kw)
            led = repo.working_ledger()
    finally:
        repo.close()
    return {
        'id': name, 'title': title,
        'runs': [{'run': 1, 'mode': ev['mode'], 'action': ev['action'], 'reasons': ev.get('reasons'),
                  'reason': ev.get('reason') or ev.get('failure'), 'push_calls': len(push.calls),
                  'recipient': ev.get('recipient')}],
        'push_calls_total': len(push.calls),
        'ledger_after': _ledger_summary(led),
        'expect': expect,
    }


def _sequence(name, title, w, plan, expect, flow='new', note=None):
    """多次排程。plan 每列：push 結果序列、ledger 提交是否成功、資料提交是否成功。"""
    repo = Repo(w)
    runs, total = [], 0
    try:
        with env(True):
            for k, p in enumerate(plan, 1):
                push = MockPush(p.get('push'))
                steps, ev = scheduled_run(repo, push, flow=flow, ledger_commit_ok=p.get('ledger_ok', True),
                                          data_commit_ok=p.get('data_ok', True))
                total += len(push.calls)
                runs.append({'run': k, 'label': p.get('label'), 'mode': ev['mode'], 'action': ev['action'],
                             'push_calls': len(push.calls), 'recipient': ev.get('recipient'), 'steps': steps,
                             'committed_ledger': _ledger_summary(repo.committed['ledger']),
                             'committed_quote': repo.committed['quote']})
    finally:
        repo.close()
    out = {'id': name, 'title': title, 'flow': flow, 'runs': runs, 'push_calls_total': total, 'expect': expect}
    if note:
        out['note'] = note
    return out


def _actual_dry_run():
    with env(False):
        ev = wh_notify.run(ROOT, dry_run=True)
    keep = ('mode', 'action', 'ready', 'reasons', 'reason', 'stock_date', 'from', 'to', 'from_name', 'to_name',
            'down', 'up', 'conc', 'delivery')
    return {
        'id': 'actual-repo-dry-run',
        'title': f'實際資料 dry-run（repo 現有 docs/wh.json，stock_date={ev.get("stock_date")}）',
        'runs': [{'run': 1, **{k: ev.get(k) for k in keep}, 'push_calls': 0}],
        'push_calls_total': 0,
        'ledger_after': '未寫入（dry-run）',
        'expect': {'mode': 'dry-run', 'delivery': 'not_sent'},
    }


def scenarios():
    S = []
    S.append(_sequence('change-sends', '狀態變化 → 推播', fixture([0, -1]),
                       [{'label': '第一次排程', 'push': [200]}],
                       {'actions': ['sent'], 'push_calls_total': 1}))
    S.append(_single('unchanged-noop', '狀態不變 → 不推', fixture([-1, -1]),
                     {'actions': ['noop'], 'push_calls_total': 0}))
    S.append(_sequence('same-day-rerun-dedup', '同日重跑（資料提交前又跑一次正式步驟）→ 去重不重推', fixture([0, 1]),
                       [{'label': '第一次：送達，ledger 提交成功，資料提交失敗', 'push': [200], 'data_ok': False},
                        {'label': '第二次：行情檔未在遠端，重跑正式步驟', 'push': [200]},
                        {'label': '第三次：行情檔已在遠端，只跑 retry-only', 'push': [200]}],
                       {'actions': ['sent', 'dedup', 'dedup'], 'push_calls_total': 1}))
    S.append(_sequence('fail-then-retry', '推播失敗 → 下次排程重試', fixture([0, 2]),
                       [{'label': '第一次：3 次都失敗，寫 failed', 'push': [False, False, RuntimeError('HTTP 500')]},
                        {'label': '第二次：retry-only 補送成功', 'push': [200]},
                        {'label': '第三次：retry-only 已送達，去重', 'push': [200]}],
                       {'actions': ['failed', 'sent', 'dedup'], 'push_calls_total': 4}))
    S.append(_single('retry-only-no-record', 'retry-only 但 ledger 沒有失敗紀錄 → 不送', fixture([0, -1]),
                     {'actions': ['skip'], 'push_calls_total': 0}, retry_only=True, expect_date=DAY))
    S.append(_single('no-secrets', '未設定 LINE secrets → 不送、不寫 ledger', fixture([0, -1]),
                     {'actions': ['skipped_no_secrets'], 'push_calls_total': 0, 'ledger_after': None}, secrets=False))
    nr = [
        ('not-ready-quote-missing', '當日行情檔不存在', fixture([0, -1]), {'quote': False}, 'quote_file_missing'),
        ('not-ready-expect-date', '排程預期日與 stock_date 不同', fixture([0, -1]), {'expect_date': '20261030'}, 'expect_date_mismatch'),
        ('not-ready-short-history', '只有一個交易日', fixture([-1]), {}, 'short_history'),
        ('not-ready-length', 'state 與 dates 長度不一', None, {}, 'length_mismatch'),
        ('not-ready-score-missing', '非常態但該側分數缺值', fixture([0, -1], down=[0.5, None]), {}, 'abnormal_score_missing'),
        ('not-ready-threshold', '檔內門檻與程式不一致', fixture([0, -1], th={'down': [0.9, 0.7], 'up': TH['up'], 'conc': TH['conc']}), {}, 'threshold_mismatch'),
    ]
    for name, title, w, kw, code in nr:
        if w is None:
            w = fixture([0, 0, -1])
            w['ext']['state'] = [0, -1]
        quote = kw.pop('quote', True)
        S.append(_single(name, f'資料不足／未就緒：{title} → 不推', w,
                         {'actions': ['not_ready'], 'push_calls_total': 0, 'reason_code': code}, quote=quote, **kw))
    # ledger 與 git 提交失敗
    S.append(_sequence('ledger-old-flow-sent-commit-fail', '舊流程：送達但當日資料提交失敗 → 乾淨 checkout 丟 ledger，下次重送',
                       fixture([0, -1]),
                       [{'label': '第一次：送達，資料提交（含 ledger）失敗', 'push': [200], 'data_ok': False},
                        {'label': '第二次：乾淨 checkout 沒有 ledger 與行情檔，重跑正式步驟', 'push': [200]}],
                       {'actions': ['sent', 'sent'], 'push_calls_total': 2}, flow='old',
                       note='修正前的行為：重複推播一次。'))
    S.append(_sequence('ledger-new-flow-sent-data-fail', '新流程：送達、ledger 先單獨提交成功、資料提交失敗 → 下次去重',
                       fixture([0, -1]),
                       [{'label': '第一次：送達，ledger 單獨提交成功，資料提交失敗', 'push': [200], 'data_ok': False},
                        {'label': '第二次：ledger 已在遠端，重跑正式步驟 → dedup', 'push': [200]}],
                       {'actions': ['sent', 'dedup'], 'push_calls_total': 1}))
    S.append(_sequence('ledger-new-flow-failed-data-fail', '新流程：推播失敗＋資料提交失敗（ledger 已單獨提交）→ 下次重試',
                       fixture([0, 1]),
                       [{'label': '第一次：推播失敗，ledger(failed) 單獨提交成功，資料提交失敗', 'push': [False, False, False], 'data_ok': False},
                        {'label': '第二次：行情檔未在遠端，重跑正式步驟；ledger 有 failed → 補送', 'push': [200]},
                        {'label': '第三次：行情檔已在遠端，retry-only → dedup', 'push': [200]}],
                       {'actions': ['failed', 'sent', 'dedup'], 'push_calls_total': 4}))
    S.append(_sequence('ledger-both-commits-fail-failed', '已知風險（可自癒）：推播失敗＋兩段提交都失敗 → ledger 丟失，下次重跑正式步驟仍會再送',
                       fixture([0, 2]),
                       [{'label': '第一次：推播失敗，ledger 與資料提交都失敗', 'push': [False, False, False], 'ledger_ok': False, 'data_ok': False},
                        {'label': '第二次：乾淨 checkout 無 ledger、無行情檔 → 正式步驟重送', 'push': [200]}],
                       {'actions': ['failed', 'sent'], 'push_calls_total': 4},
                       note='ledger 丟失，但因行情檔也沒提交，下次排程走正式步驟而不是 retry-only，所以仍會補送。若這是當日最後一次排程（18:20），當日就沒有下一次，需人工補救。'))
    S.append(_sequence('ledger-both-commits-fail-sent', '已知風險（會重複）：送達＋兩段提交都失敗 → 下次重送一次',
                       fixture([0, -1]),
                       [{'label': '第一次：送達，ledger 與資料提交都失敗', 'push': [200], 'ledger_ok': False, 'data_ok': False},
                        {'label': '第二次：乾淨 checkout 無 ledger → 再送一次（重複）', 'push': [200]}],
                       {'actions': ['sent', 'sent'], 'push_calls_total': 2},
                       note='無法在 repo 內完全修好：送達事實只寫在 runner 的工作目錄。workflow 會上傳 ledger artifact 供人工補提交。'))
    S.append(_sequence('ledger-retry-commit-fail', '已知風險（會重複）：retry-only 補送成功但提交失敗 → 下次 retry-only 再送',
                       fixture([0, 1]),
                       [{'label': '第一次：推播失敗，提交成功', 'push': [False, False, False]},
                        {'label': '第二次：retry-only 補送成功，提交失敗', 'push': [200], 'ledger_ok': False},
                        {'label': '第三次：遠端 ledger 仍是 failed → 再送', 'push': [200]}],
                       {'actions': ['failed', 'sent', 'sent'], 'push_calls_total': 5}))
    S.append(_actual_dry_run())
    return S


def check(s):
    exp = s['expect']
    acts = [r['action'] for r in s['runs']]
    problems = []
    if 'actions' in exp and acts != exp['actions']:
        problems.append(f'actions {acts} != {exp["actions"]}')
    if 'push_calls_total' in exp and s['push_calls_total'] != exp['push_calls_total']:
        problems.append(f'push_calls {s["push_calls_total"]} != {exp["push_calls_total"]}')
    if 'reason_code' in exp and exp['reason_code'] not in (s['runs'][0].get('reasons') or []):
        problems.append(f'reason {exp["reason_code"]} missing')
    if 'ledger_after' in exp and s.get('ledger_after') != exp['ledger_after']:
        problems.append('ledger_after mismatch')
    if 'mode' in exp:
        r = s['runs'][0]
        if r.get('mode') != exp['mode'] or r.get('delivery') != exp['delivery']:
            problems.append('dry-run 不應送出')
    return problems


def _md(out):
    L = [
        '# 市場狀態推播：dry-run 證據',
        '',
        f"由 `python3 scripts/wh_notify_evidence.py` 產生。mock push 取代 LINE，不連網；規則 `{out['rule']}`。",
        f"全部情境：**{'符合預期' if out['pass'] else '有落差'}**（{sum(1 for s in out['scenarios'] if not s['problems'])}／{len(out['scenarios'])}）。",
        '收件者一律遮蔽為 `configured`（有 secrets）或 `unset`；mock token／user id 已檢查未出現在任何輸出。'
        '時間戳為固定假時鐘，便於重跑比對。',
        '',
        '## 情境總表',
        '',
        '| id | 情境 | 每次排程結果 | mock push 次數 | 符合 |',
        '| --- | --- | --- | ---: | --- |',
    ]
    for s in out['scenarios']:
        acts = ' → '.join(r['action'] for r in s['runs'])
        L.append(f"| {s['id']} | {s['title']} | {acts} | {s['push_calls_total']} | {'是' if not s['problems'] else '否：' + '；'.join(s['problems'])} |")
    L += ['', '## 逐次執行紀錄', '']
    for s in out['scenarios']:
        L.append(f"### {s['id']}")
        L.append('')
        L.append(s['title'] + (f"（流程：{s['flow']}）" if s.get('flow') else ''))
        if s.get('note'):
            L.append('')
            L.append(f"> {s['note']}")
        L.append('')
        for r in s['runs']:
            head = f"- 第 {r['run']} 次" + (f"（{r['label']}）" if r.get('label') else '')
            L.append(f"{head}：mode=`{r['mode']}` action=`{r['action']}` push={r['push_calls']}"
                     + (f" recipient=`{r['recipient']}`" if r.get('recipient') else '')
                     + (f" reasons={r['reasons']}" if r.get('reasons') else '')
                     + (f" reason=`{r['reason']}`" if r.get('reason') else ''))
            for st in r.get('steps') or []:
                if st.get('git'):
                    L.append(f"  - {st['step']}：git `{st['git']}`")
            if 'committed_ledger' in r:
                cl = r['committed_ledger']
                L.append('  - 遠端 ledger：' + ('無' if not cl else '、'.join(f"{x['from']}→{x['to']} {x['result']}" for x in cl))
                         + f"；遠端行情檔：{'有' if r['committed_quote'] else '無'}")
        L.append('')
    L += [
        '## ledger 與 git 提交失敗：結論',
        '',
        '- 修正前（`ledger-old-flow-sent-commit-fail`）：ledger 只跟著「提交更新」整包提交。該次 push 失敗時，乾淨 checkout 沒有 ledger，'
        '行情檔也不在，下次排程重跑正式步驟：若上次其實已送達就重複推一次；若上次失敗則會補送。',
        '- 修正後：`daily.yml` 在推播步驟後**先單獨提交並 push ledger（5 次重試）**，再提交整包資料。資料提交失敗時，下次排程看得到 ledger，'
        '已送達的去重、失敗的補送（`ledger-new-flow-*`）。單獨 push 也失敗時會把 ledger 上傳成 workflow artifact `wh-notify-ledger-<run_id>`。',
        '- 仍有的已知風險：兩段提交都失敗，或 retry-only 補送成功後提交失敗，下次可能**重複推一次**；若那是當日最後一次排程，失敗的事件當日不會再自動補送。'
        '人工補救步驟見 `docs/wh-market-state-rules.md` 第 6 節。',
        '',
    ]
    return '\n'.join(L)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--check', action='store_true', help='只比對預期，不寫檔')
    args = p.parse_args(argv)
    S = scenarios()
    for s in S:
        s['problems'] = check(s)
    out = {
        'generated_by': 'scripts/wh_notify_evidence.py',
        'rule': wh_extreme.RULE_ID,
        'push': 'mock（不連網、不打 LINE）',
        'recipient_masking': 'configured／unset；不含 token、user id',
        'pass': all(not s['problems'] for s in S),
        'scenarios': S,
    }
    blob = json.dumps(out, ensure_ascii=False, indent=2)
    leaked = MOCK_TOKEN in blob or MOCK_USER in blob
    if leaked:
        out['pass'] = False
        print('mock secrets 出現在輸出', file=sys.stderr)
    if not args.check:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, 'notify.json'), 'w', encoding='utf-8') as f:
            f.write(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
        with open(os.path.join(OUT, 'notify.md'), 'w', encoding='utf-8') as f:
            f.write(_md(out))
    for s in S:
        print(('ok  ' if not s['problems'] else 'FAIL'), s['id'], ' → '.join(r['action'] for r in s['runs']), s['problems'] or '')
    return 0 if out['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
