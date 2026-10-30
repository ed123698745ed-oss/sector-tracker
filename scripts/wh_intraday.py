"""權值與高價股分頁：盤中暫定（約每 5 分鐘）。

從證交所「基本市況報導」（mis.twse.com.tw，涵蓋上市與上櫃）查加權指數、全市場上市櫃普通股（約 1,950 檔，
每次 100 檔一批、約 20 次查詢、2 分鐘內完成）的最新成交，算全市場漲跌家數、漲跌停與分布，並保留個股表各檔價格，
寫成 wh_intraday.json，強制推到 repo 的 live 分支（單一 commit，不進 main、不觸發 Pages 重建）。
網頁由 raw.githubusercontent.com 讀取；收盤正式資料（wh.json）日期追上後網頁自動改回收盤資料。

只供觀察，不是交易訊號。

防錯（對照《00_Emit事故檢討與建置防錯清單》）：
  - 日期用報價自帶的 d，不是今天就不寫（休市、颱風）。
  - 回傳檔數低於應查檔數 90% 不寫，推一次 LINE 異常通知。
  - 連續 3 次抓取失敗推一次 LINE 異常通知。
  - 只在台北 09:00～13:36 執行；排程延遲到收盤後就直接結束。
  - base_date 記錄所用收盤資料日，網頁只在 base_date 等於 wh.json 最後一日時才採用。

  python3 scripts/wh_intraday.py            抓一次，寫 docs-live/wh_intraday.json（不推）
  python3 scripts/wh_intraday.py --loop --push   盤中每 5 分鐘抓一次並推到 live 分支
"""
import datetime
import json
import os
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glob  # noqa: E402
import intraday  # noqa: E402
from intraday import fetch, price, pct, at_limit_up, market_of, alert_once, TPE, ROOT  # noqa: E402
from wh_prices import is_common  # noqa: E402

intraday.BATCH = 100  # 2026-10-30 實測：100 檔一批正常回傳，200 檔回傳 0 筆、400 檔 URI 過長


def universe():
    """全市場上市櫃普通股：最近一份有資料的收盤行情檔裡的普通股代號（與 wh_build 全市場口徑相同）。"""
    for f in sorted(glob.glob(os.path.join(ROOT, 'data', 'quotes', '*.json')), reverse=True):
        q = json.load(open(f, encoding='utf-8')).get('q') or {}
        cs = sorted(c for c in q if is_common(c))
        if cs:
            return cs, os.path.basename(f)[:8]
    return [], None


def dist(ps):
    b = [0] * 11
    for p in ps:
        k = (0 if p <= -9 else 1 if p <= -5 else 2 if p <= -3 else 3 if p <= -1 else 4 if p < 0 else 5 if p == 0
             else 6 if p < 1 else 7 if p < 3 else 8 if p < 5 else 9 if p < 9 else 10)
        b[k] += 1
    return b

OUT_DIR = os.path.join(ROOT, 'live-out')
OUT = os.path.join(OUT_DIR, 'wh_intraday.json')
START, END = '0900', '1336'
STEP = 300  # 秒
COUNT_MIN = 0.9


def at_limit_down(x):
    try:
        w, z = float(x.get('w') or 0), price(x)
        return bool(w and z and z <= w + 1e-6)
    except ValueError:
        return False


def num(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def snapshot(w, tse, uni, now=None):
    """回傳 (out, lines)。out 為 None 表示這次不寫。"""
    now = now or datetime.datetime.now(TPE)
    codes = sorted(set(uni) | {r['c'] for r in w['stocks']})
    t0 = time.time()
    q, stat = fetch(codes, tse)
    ix, st2 = fetch(['t00'], {'t00'})
    lines = [f"run_at {now.strftime('%Y-%m-%d %H:%M:%S')} codes {len(codes)} returned {len(q)} "
             f"seconds {round(time.time() - t0, 1)} requests {stat['requests'] + st2['requests']} "
             f"errors {stat['errors'] + st2['errors']} {stat.get('last_error', '') or st2.get('last_error', '')}"]
    qd = Counter(x.get('d') for x in list(q.values()) + list(ix.values()) if x.get('d')).most_common(1)
    qdate = qd[0][0] if qd else None
    if qdate != now.strftime('%Y%m%d'):
        lines.append(f'skip: quote date {qdate} != today（休市或尚無今日報價）')
        return None, lines
    if len(q) < len(codes) * COUNT_MIN:
        lines.append(f'skip: returned {len(q)} < {COUNT_MIN:.0%} of {len(codes)}')
        alert_once('wh_count', qdate,
                   f"【權值高價股・盤中異常】{now.strftime('%m/%d %H:%M')}\n盤中只抓到 {len(q)}／{len(codes)} 檔報價，"
                   f"低於 90%，已停止更新盤中資料，網頁維持上一筆。請 Emit 檢查。")
        return None, lines
    t = ix.get('t00') or {}
    tx, ty = num(t.get('z')), num(t.get('y'))
    if tx is None or ty is None:
        lines.append('skip: 加權指數無報價')
        return None, lines
    want, uset = {r['c'] for r in w['stocks']}, set(uni)
    stocks, priced, ps, lu, ld = {}, 0, [], 0, 0
    for c, x in q.items():
        p = pct(x)
        if p is None:
            continue
        priced += 1
        lim = 1 if at_limit_up(x) else (-1 if at_limit_down(x) else 0)
        if c in want:
            stocks[c] = [price(x), p, lim]
        if c in uset:
            ps.append(p); lu += lim == 1; ld += lim == -1
    allg = {'n': len(ps), 'up': sum(p > 0 for p in ps), 'flat': sum(p == 0 for p in ps), 'down': sum(p < 0 for p in ps),
            'lu': lu, 'ld': ld, 'dist': dist(ps), 'universe': len(uni)}
    times = sorted(x.get('t') for x in q.values() if x.get('t'))
    out = {'date': qdate, 'time': now.strftime('%H:%M'), 'quote_time': max(times[-1:] + [t.get('t') or '']) or None,
           'base_date': w['dates'][-1], 'taiex': tx, 'taiex_y': ty, 'n': len(codes), 'priced': priced,
           'source': '臺灣證券交易所 基本市況報導（mis.twse.com.tw）', 'all': allg, 'stocks': stocks}
    lines.append(f"ok date {qdate} taiex {tx} ({(tx / ty - 1) * 100:+.2f}%) priced {priced}/{len(codes)} "
                 f"all n {allg['n']} up {allg['up']} down {allg['down']} lu {lu} ld {ld} base {w['dates'][-1]}")
    return out, lines


def push_live(path):
    tok, repo = os.environ.get('GH_TOKEN'), os.environ.get('GITHUB_REPOSITORY')
    if not (tok and repo):
        return 'skip push: no GH_TOKEN/GITHUB_REPOSITORY'
    d = os.path.join(os.environ.get('RUNNER_TEMP', '/tmp'), 'wh-live')
    os.makedirs(d, exist_ok=True)
    run = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True, text=True)
    if not os.path.isdir(os.path.join(d, '.git')):
        run('git', 'init', '-q')
        run('git', 'checkout', '-q', '-b', 'live')
        run('git', 'config', 'user.name', 'sector-tracker-bot')
        run('git', 'config', 'user.email', 'actions@users.noreply.github.com')
    with open(path, 'rb') as a, open(os.path.join(d, 'wh_intraday.json'), 'wb') as b:
        b.write(a.read())
    run('git', 'add', 'wh_intraday.json')
    # 只保留單一 commit：每次重建，強制推送
    subprocess.run(['git', 'update-ref', '-d', 'HEAD'], cwd=d, capture_output=True)
    run('git', 'commit', '-q', '-m', '權值高價股盤中暫定 [skip ci]')
    url = f'https://x-access-token:{tok}@github.com/{repo}.git'
    for k in range(3):
        r = subprocess.run(['git', 'push', '-f', '-q', url, 'live'], cwd=d, capture_output=True, text=True)
        if r.returncode == 0:
            return 'pushed'
        time.sleep(5)
    return 'push failed: ' + r.stderr.replace(tok, '[redacted]')[:200]


def main(argv):
    loop, do_push = '--loop' in argv, '--push' in argv
    w = json.load(open(os.path.join(ROOT, 'docs', 'wh.json'), encoding='utf-8'))
    tse = market_of()
    uni, uday = universe()
    print(f'universe {len(uni)} from {uday}', flush=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    fails = 0
    while True:
        now = datetime.datetime.now(TPE)
        hm = now.strftime('%H%M')
        if now.weekday() >= 5 or hm > END:
            print('非盤中時間，結束', now.strftime('%Y-%m-%d %H:%M'))
            return 0
        if hm < START:
            if not loop:
                print('尚未開盤')
                return 0
            time.sleep(30)
            continue
        try:
            out, lines = snapshot(w, tse, uni, now)
        except Exception as e:  # 單次失敗不中斷整個盤中迴圈
            out, lines = None, [f"error {now.strftime('%H:%M:%S')} {str(e)[:200]}"]
        if out:
            fails = 0
            with open(OUT, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
            if do_push:
                lines.append(push_live(OUT))
        else:
            fails += 1
            if fails == 3:
                alert_once('wh_fail', now.strftime('%Y%m%d'),
                           f"【權值高價股・盤中異常】{now.strftime('%m/%d %H:%M')}\n盤中資料連續 3 次未更新：{lines[-1][:120]}\n請 Emit 檢查。")
        print('\n'.join(lines), flush=True)
        if not loop:
            return 0
        nxt = (int(time.time()) // STEP + 1) * STEP
        time.sleep(max(5, nxt - time.time()))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
