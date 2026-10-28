"""抓證交所「外資及陸資投資持股統計」(MI_QFIIS) 各排名日原始檔，取每檔上市股票當日「發行股數」。
此表含當時所有上市股票（包含之後已下市者），用來補財報彙總表的倖存者缺口並交叉核對股數。
用法：python3 fetch_qfiis.py <dates.json>；原始檔存 archive/raw/twse_qfiis/YYYYMMDD.json.gz，已存在者略過。
"""
import gzip, json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'archive', 'raw', 'twse_qfiis')


def main():
    os.makedirs(OUT, exist_ok=True)
    got = 0
    for ds in json.load(open(sys.argv[1])):
        f = os.path.join(OUT, ds + '.json.gz')
        if os.path.exists(f): continue
        u = f'https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date={ds}&selectType=ALLBUT0999&response=json'
        for wait in (10, 30, 60, 120, 240):
            try:
                b = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=90).read()
                d = json.loads(b)
                if d.get('stat') == 'OK' and d.get('data'):
                    gzip.open(f, 'wb').write(b); got += 1; print('got', ds, len(d['data']), flush=True); break
                print('stat', ds, d.get('stat'), flush=True)
            except Exception as e:
                print('err', ds, repr(e)[:80], flush=True)
            time.sleep(wait)
        if os.environ.get('GITHUB_ACTIONS') and got and got % 30 == 0:
            subprocess.run('git add archive/raw/twse_qfiis && git commit -qm "MI_QFIIS 進度 [skip ci]" && '
                           'for i in 1 2 3; do git pull --rebase -q && git push -q && break; sleep 5; done', shell=True, cwd=ROOT)
        time.sleep(6)
    print('done', flush=True)


if __name__ == '__main__':
    main()
