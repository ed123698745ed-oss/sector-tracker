"""權值與高價股觀察：歷史往前延伸所需的證交所資料（GitHub Actions 執行）。

1. 大盤日成交資訊 FMTQIK（每月一檔）：2004/02～2014/12，取加權指數收盤與交易日（2009 年前 MI_INDEX 無指數表）
2. 依 FMTQIK 交易日找各月最後交易日 → 抓 MI_QFIIS 發行股數（fetch_qfiis.py）
3. 除權息 TWT49U、變更面額 TWTB8U：2004～2014；減資 TWTAUU：2011～2014（證交所只提供 2011 年起）
已存在的檔案略過。
"""
import datetime as dt, json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FM = os.path.join(ROOT, 'archive', 'raw', 'twse_fmtqik')
EV = os.path.join(ROOT, 'archive', 'raw', 'twse_events')


def get(u):
    for wait in (10, 30, 90, 180):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=90).read()
            j = json.loads(b)
            return b, j
        except Exception as e:
            print('err', u, repr(e)[:80], flush=True); time.sleep(wait)
    raise SystemExit('抓取失敗 ' + u)


def main():
    os.makedirs(FM, exist_ok=True); os.makedirs(EV, exist_ok=True)
    ends = []
    y, m = 2004, 2
    while (y, m) <= (2014, 12):
        f = os.path.join(FM, '%d%02d.json' % (y, m))
        if not os.path.exists(f):
            b, j = get(f'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={y}{m:02d}01&response=json')
            if j.get('stat') != 'OK': raise SystemExit(f'FMTQIK {y}{m:02d} {j.get("stat")}')
            open(f, 'wb').write(b); print('FMTQIK', y, m, flush=True); time.sleep(4)
        rows = json.load(open(f))['data']
        a, b_, c = rows[-1][0].strip().split('/')
        ends.append('%d%s%s' % (int(a) + 1911, b_, c))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    tgt = [e for e in ends if e < '20150101']
    p = os.path.join(ROOT, 'cache', 'wh_ext_qfiis.json'); os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(tgt, open(p, 'w'))
    for yy in range(2004, 2015):
        for k, ctl in (('TWT49U', 'exRight'), ('TWTB8U', 'change'), ('TWTAUU', 'reducation')):
            if k == 'TWTAUU' and yy < 2011: continue
            f = os.path.join(EV, f'{k}_{yy}.json')
            if os.path.exists(f): continue
            b, j = get(f'https://www.twse.com.tw/rwd/zh/{ctl}/{k}?startDate={yy}0101&endDate={yy}1231&response=json')
            if j.get('stat') != 'OK': raise SystemExit(f'{k} {yy} {j.get("stat")}')
            open(f, 'wb').write(b); print(k, yy, len(j.get('data') or []), flush=True); time.sleep(5)
    subprocess.run(['git', 'add', 'archive/raw/twse_fmtqik', 'archive/raw/twse_events'], cwd=ROOT)
    subprocess.run('git commit -qm "權值高價股歷史延伸：大盤指數與事件表 [skip ci]" && for i in 1 2 3 4 5; do git pull --rebase -q && git push -q && break; sleep 10; done', shell=True, cwd=ROOT)
    subprocess.run([sys.executable, 'scripts/fetch_qfiis.py', p], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
