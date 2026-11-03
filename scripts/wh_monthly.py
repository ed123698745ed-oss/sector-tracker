"""權值與高價股觀察：每月名單更新（每日排程呼叫，新月份才有動作）。

1. 已結束月份的最後交易日若缺證交所 MI_QFIIS 發行股數 → 補抓
2. 重抓今年（1 月時含去年）證交所減資 TWTAUU、變更面額 TWTB8U、除權息 TWT49U 全年表
3. 跑 wh_lists.py；近 120 日內「權息」事件缺配股率且屬上市市值前 80 者 → 抓除權息基準日公告後重跑
4. 已存在的月份一律保留原名單（R06 凍結，Ed 2026-10-28），只新增月份；新月份缺上市名單即報錯
   wh_lists.py 會直接覆寫 config/wh_lists.json：任何一步失敗都還原成執行前的內容（2026-11-03 檢驗報告第 3 項），
   wh_build 因此沿用上月名單，隔天排程會再補這個月份
"""
import datetime as dt, json, os, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LISTS = os.path.join(ROOT, 'config', 'wh_lists.json')
EV = {'TWT49U': 'exRight', 'TWTAUU': 'reducation', 'TWTB8U': 'change'}


def get(u):
    """抓取，失敗退避重試 4 次（檢驗報告次要項目：原本沒有重試）"""
    import time
    for i in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=90).read()
        except Exception as e:
            print('retry', i, u, repr(e)[:80], flush=True)
            time.sleep(15 * (i + 1))
    raise RuntimeError(f'抓取失敗：{u}')


def run(*a):
    subprocess.run([sys.executable, *a], cwd=ROOT, check=True)


def main():
    days = sorted(f[:8] for f in os.listdir(os.path.join(ROOT, 'data', 'quotes')) if f.endswith('.json') and f >= '20150101')
    ends = {}
    for d in days: ends[d[:6]] = d
    ends.pop(days[-1][:6], None)
    old_bytes = open(LISTS, 'rb').read()
    old = json.loads(old_bytes)
    new_months = [ym for ym in sorted(ends) if ym not in old]
    if not new_months:
        print('名單無新月份'); return
    print('新月份', new_months)
    try:
        update(days, ends, old, new_months)
    except BaseException:
        open(LISTS, 'wb').write(old_bytes)   # 先寫後驗失敗：還原，不留半成品名單
        print('::error::名單月更新失敗，config/wh_lists.json 已還原，沿用上月名單', flush=True)
        raise


def update(days, ends, old, new_months):
    # 1. MI_QFIIS
    tgt = [ends[ym] for ym in new_months]
    p = os.path.join(ROOT, 'cache', 'wh_qfiis_targets.json'); os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(tgt, open(p, 'w')); run('scripts/fetch_qfiis.py', p)
    # 2. 事件表
    y = int(days[-1][:4]); years = {y} | {int(ends[ym][:4]) for ym in new_months}
    for yy in sorted(years):
        for k, ctl in EV.items():
            u = f'https://www.twse.com.tw/rwd/zh/{ctl}/{k}?startDate={yy}0101&endDate={yy}1231&response=json'
            b = get(u); j = json.loads(b)
            if j.get('stat') != 'OK': raise SystemExit(f'{k} {yy} 抓取失敗：{j.get("stat")}')
            if not isinstance(j.get('data', []), list) or not j.get('fields') or len(j['fields']) < 5:
                raise SystemExit(f'{k} {yy} 格式不符：fields={j.get("fields")}')   # 驗格式再寫檔
            open(os.path.join(ROOT, 'archive', 'raw', 'twse_events', f'{k}_{yy}.json'), 'wb').write(b)
    # 3. 名單＋配股率補件
    run('scripts/wh_prices.py'); run('scripts/wh_lists.py')
    ev = json.load(open(os.path.join(ROOT, 'cache', 'wh_share_events.json')))
    r80 = set(json.load(open(os.path.join(ROOT, 'cache', 'wh_rank80.json'))))
    lo = (dt.date(int(tgt[0][:4]), int(tgt[0][4:6]), int(tgt[0][6:])) - dt.timedelta(days=120)).strftime('%Y%m%d')
    miss = sorted({(c, ds) for ds, c, why in ev['unsplit'] if why == 'stock_rate_missing' and ds > lo and c in r80})
    if miss:
        print('補抓配股率', miss)
        p = os.path.join(ROOT, 'cache', 'wh_divn_targets.json'); json.dump([list(m) for m in miss], open(p, 'w'))
        run('scripts/fetch_div_notice.py', p); run('scripts/wh_lists.py')
        ev = json.load(open(os.path.join(ROOT, 'cache', 'wh_share_events.json')))
        left = [(c, ds) for ds, c, why in ev['unsplit'] if why == 'stock_rate_missing' and ds > lo and c in r80]
        if left: print('::warning::仍缺配股率（未調整股數）', left)
    # 4. 凍結舊月份
    cur = json.load(open(LISTS))
    for ym in new_months:
        if not cur.get(ym, {}).get('twse'): raise SystemExit(f'{ym} 上市名單產生失敗')
    merged = dict(old); merged.update({ym: cur[ym] for ym in new_months})
    json.dump(merged, open(LISTS, 'w'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    print('名單新增', new_months)


if __name__ == '__main__':
    main()
