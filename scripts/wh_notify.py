"""權值與高價股分頁：市場狀態（非常態判定）改變時推 LINE。

只推觀察訊息，不含買賣建議。Ed 2026-10-30 指示暫停推播：daily.yml 兩個推播步驟已設 if: false，本檔保留供恢復時使用。

排程（`.github/workflows/daily.yml`）：
  台北時間週一至週五 13:52、14:12、14:32、14:52、15:12、15:42、16:20、18:20。
  收盤檔 `data/quotes/當日.json` 已存在則整段計算跳過。
  同日若先前失敗且 ledger 有失敗紀錄，後續排程只跑 `--retry-only` 補送並提交 ledger。
  正式步驟之後，ledger 先單獨 commit／push（5 次重試），再提交整包資料；單獨 push 失敗則上傳 artifact。
  情境證據：`python3 scripts/wh_notify_evidence.py` → docs/wh-market-state-evidence/notify.md。

資料就緒：wh.json 的 stock_date 須等於最後一個 dates、長度一致、當日行情檔存在、
  門檻與程式一致；若傳入 --expect-date 則必須等於該日。非常態但對應分數缺值則不送。

去重：`data/wh_notify_ledger.json` 以（資料日、前態、新態）記錄已送達。同一鍵已 sent 則不重送。
  同日重跑若狀態沒變，本來就不推。修訂後若變成另一組前態／新態，視為新事件會再送。

重試：同一次執行內 HTTP 失敗最多 3 次（間隔 2 秒、4 秒）。仍失敗寫入 ledger result=failed。
  下次 `--retry-only` 只補送「已有失敗紀錄」的同一事件；沒有紀錄不補送，避免舊版已送過但尚未寫 ledger 時再送一次。

紀錄：ledger 只寫 result、次數、時間、分數與訊息正文。收件者只記 configured 或 unset，不寫 LINE token／user id。
  未設定 secrets 時不標成已送達。

  python3 scripts/wh_notify.py --dry-run
  python3 scripts/wh_notify.py --preview-test     # 只印「測試」訊息，不送
  python3 scripts/wh_notify.py --expect-date 20261029 --dry-run
  python3 scripts/wh_notify.py --retry-only --expect-date 20261029
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify import push  # noqa: E402
import wh_extreme  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = wh_extreme.STATE_NAME
LEDGER_NAME = os.path.join('data', 'wh_notify_ledger.json')
TPE = timezone(timedelta(hours=8))


def _now():
    return datetime.now(TPE).isoformat(timespec='seconds')


def _norm_date(s):
    if not s:
        return None
    return str(s).replace('-', '')


def ledger_path(root=None):
    return os.path.join(root or ROOT, LEDGER_NAME)


def load_ledger(path):
    if not os.path.exists(path):
        return {'version': 1, 'records': []}
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    data.setdefault('version', 1)
    data.setdefault('records', [])
    return data


def save_ledger(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, path)


def find_record(data, stock_date, prev, curr):
    for rec in reversed(data.get('records') or []):
        if rec.get('stock_date') == stock_date and rec.get('from') == prev and rec.get('to') == curr:
            return rec
    return None


def load_wh(root=None):
    path = os.path.join(root or ROOT, 'docs', 'wh.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def readiness(w, root=None, expect_date=None, check_quotes=True):
    """回傳 (ok, reasons)。reasons 為機器可讀代碼。"""
    reasons = []
    root = root or ROOT
    if not isinstance(w, dict) or 'ext' not in w or 'dates' not in w:
        return False, ['missing_ext']
    e, dates = w['ext'], w['dates']
    if not isinstance(dates, list) or len(dates) < 2:
        reasons.append('short_history')
    n = len(dates) if isinstance(dates, list) else 0
    for k in ('state', 'dd', 'ru', 'conc'):
        if not isinstance(e.get(k), list) or len(e[k]) != n:
            reasons.append('length_mismatch')
            break
    stock_date = str(w.get('stock_date') or '')
    if n and stock_date != dates[-1]:
        reasons.append('stock_date_not_last')
    if check_quotes and stock_date:
        q = os.path.join(root, 'data', 'quotes', stock_date + '.json')
        if not os.path.exists(q):
            reasons.append('quote_file_missing')
    exp = _norm_date(expect_date)
    if exp and stock_date != exp:
        reasons.append('expect_date_mismatch')
    file_th = e.get('th') or {}
    for k, (a, b) in wh_extreme.TH.items():
        pair = file_th.get(k)
        if not pair or len(pair) < 2 or abs(float(pair[0]) - a) > 1e-12 or abs(float(pair[1]) - b) > 1e-12:
            reasons.append('threshold_mismatch')
            break
    if n and 'length_mismatch' not in reasons:
        st = e['state'][-1]
        score = {-1: e['dd'][-1], 1: e['ru'][-1]}.get(st)
        if st != 0 and score is None:
            reasons.append('abnormal_score_missing')
    return (not reasons), reasons


def format_message(date, prev, curr, dd, ru, conc, taiex, test=False):
    pc = lambda v: '—' if v is None else f'{v * 100:+.1f}%'
    sc = lambda v: '—' if v is None else f'{v * 100:.0f}'
    th, wn = wh_extreme.TH, wh_extreme.WIN
    txl = f"加權指數 {taiex:,.0f}\n" if taiex else ''
    prefix = '【測試】' if test else ''
    return (f"{prefix}【權值高價股・市場狀態】{date[:4]}-{date[4:6]}-{date[6:]}\n"
            f"{NAME[prev]} → {NAME[curr]}\n"
            f"距{wn['down']}日高 {pc(dd)}（進入−{th['down'][0] * 100:g}%）／距{wn['up']}日低 {pc(ru)}（進入+{th['up'][0] * 100:g}%）／資金集中 {sc(conc)}（參考）\n"
            + txl + "只供觀察，不是交易訊號。\nhttps://ed123698745ed-oss.github.io/sector-tracker/wh.html")


def preview_test_message():
    """固定的測試示範，不讀秘密、不送出。"""
    return format_message('20261029', 0, -1, -0.093, 0.019, 0.595, 46368, test=True) + '\n（測試示範，未送出）'


def _public_record(stock_date, prev, curr, result, attempts, scores, message, recipient):
    return {
        'stock_date': stock_date,
        'from': prev,
        'to': curr,
        'result': result,
        'attempts': attempts,
        'at': _now(),
        'recipient': recipient,  # configured / unset；沒有 user id
        'rule': wh_extreme.RULE_ID,
        'dd': scores[0],
        'ru': scores[1],
        'conc': scores[2],
        'message_sha256': hashlib.sha256(message.encode()).hexdigest() if message else None,
        'message': message,
    }


def deliver(msg, push_fn=None, attempts=3, sleep_s=2.0):
    """有 secrets 才送。失敗重試。回傳 ok、attempts、recipient、reason。"""
    push_fn = push if push_fn is None else push_fn
    tok = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    uid = os.environ.get('LINE_USER_ID')
    if not (tok and uid):
        return {'ok': False, 'attempts': 0, 'recipient': 'unset', 'reason': 'no_secrets'}
    last_reason = 'push_failed'
    for i in range(1, attempts + 1):
        try:
            status = push_fn(msg)
        except Exception as e:
            err = str(e)
            if tok and tok in err:
                err = err.replace(tok, '[redacted]')
            if uid and uid in err:
                err = err.replace(uid, '[redacted]')
            status = False
            last_reason = err
        if status:
            return {'ok': True, 'attempts': i, 'recipient': 'configured', 'reason': 'sent', 'http_status': status}
        if i < attempts and sleep_s:
            time.sleep(sleep_s * i)
    return {'ok': False, 'attempts': attempts, 'recipient': 'configured', 'reason': last_reason}


def run(root=None, *, dry_run=False, retry_only=False, preview_test=False, expect_date=None,
        check_quotes=True, push_fn=None, attempts=3, sleep_s=2.0, ledger=None):
    """決定並（除非 dry-run）執行推播。回傳可印出的證據 dict，不含 secrets。"""
    if preview_test:
        msg = preview_test_message()
        return {'mode': 'preview-test', 'action': 'not_sent', 'test_label': True, 'message': msg}

    root = root or ROOT
    path = ledger or ledger_path(root)
    evidence = {
        'mode': 'dry-run' if dry_run else ('retry-only' if retry_only else 'send'),
        'rule': wh_extreme.RULE_ID,
        'test_label': False,
        'delivery': 'not_sent',
    }
    try:
        w = load_wh(root)
    except Exception as e:
        evidence.update({'action': 'not_ready', 'ready': False, 'reasons': ['wh_json_unreadable'], 'detail': str(e)})
        return evidence
    ok, reasons = readiness(w, root, expect_date=expect_date, check_quotes=check_quotes)
    e, dates = w.get('ext') or {}, w.get('dates') or []
    evidence.update({
        'ready': ok,
        'reasons': reasons,
        'stock_date': w.get('stock_date'),
        'expect_date': _norm_date(expect_date),
    })
    if not ok:
        evidence['action'] = 'not_ready'
        return evidence
    prev, curr = e['state'][-2], e['state'][-1]
    scores = (e['dd'][-1], e['ru'][-1], e['conc'][-1])
    evidence.update({'from': prev, 'to': curr, 'from_name': NAME[prev], 'to_name': NAME[curr],
                     'dd': scores[0], 'ru': scores[1], 'conc': scores[2]})
    if prev == curr:
        evidence.update({'action': 'noop', 'reason': 'state_unchanged'})
        return evidence
    msg = format_message(dates[-1], prev, curr, scores[0], scores[1], scores[2], w['taiex'][-1], test=False)
    evidence['message'] = msg
    led = load_ledger(path)
    rec = find_record(led, dates[-1], prev, curr)
    if rec and rec.get('result') == 'sent':
        evidence.update({'action': 'dedup', 'reason': 'already_sent', 'prior_at': rec.get('at')})
        return evidence
    if retry_only and not (rec and rec.get('result') == 'failed'):
        evidence.update({'action': 'skip', 'reason': 'retry_only_without_failed_record'})
        return evidence
    if dry_run:
        evidence.update({'action': 'would_send', 'reason': 'dry_run'})
        return evidence
    result = deliver(msg, push_fn=push_fn, attempts=attempts, sleep_s=sleep_s)
    if result['reason'] == 'no_secrets':
        # 沒有送達事實，不寫 ledger，避免之後被當成已處理。
        evidence.update({'action': 'skipped_no_secrets', 'attempts': 0, 'recipient': 'unset', 'delivery': 'not_sent'})
        return evidence
    status = 'sent' if result['ok'] else 'failed'
    row = _public_record(dates[-1], prev, curr, status, result['attempts'], scores, msg, result['recipient'])
    if result.get('http_status'):
        row['http_status'] = result['http_status']
    if not result['ok']:
        row['failure'] = result['reason']
    led['records'].append(row)
    save_ledger(path, led)
    evidence.update({
        'action': status,
        'attempts': result['attempts'],
        'recipient': result['recipient'],
        'delivery': 'sent' if result['ok'] else 'not_sent',
        'ledger': os.path.relpath(path, root),
    })
    if not result['ok']:
        evidence['failure'] = result['reason']
    return evidence


def _print_evidence(ev):
    print(json.dumps(ev, ensure_ascii=False, indent=2))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = '--dry-run' in argv
    retry_only = '--retry-only' in argv
    preview = '--preview-test' in argv
    expect = None
    if '--expect-date' in argv:
        i = argv.index('--expect-date')
        expect = argv[i + 1]
    ev = run(dry_run=dry, retry_only=retry_only, preview_test=preview, expect_date=expect)
    _print_evidence(ev)
    if ev.get('action') == 'failed':
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
