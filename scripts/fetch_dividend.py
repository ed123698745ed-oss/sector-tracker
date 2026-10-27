"""抓個別公司股利分派情形（公開資訊觀測站 t05st09），取「盈餘／公積轉增資配股（元/股）」與現金股利，
供除權息同時發生（TWT49U「權息」）時拆出配股率、調整上市股數。
用法：python3 fetch_dividend.py <targets.json>   targets=[[代號, 民國年], ...]（民國年＝股東會年度）
原始檔存 archive/raw/mops_div/<代號>_<年>.html.gz；已存在者略過。每次間隔 25 秒，被擋則退避。
"""
import gzip, json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'archive', 'raw', 'mops_div')
URL = 'https://mopsov.twse.com.tw/mops/web/ajax_t05st09'
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mopsov.twse.com.tw/mops/web/t05st09'}


def get(c, y):
    body = f'step=2&firstin=1&off=1&queryName=co_id&inpuType=co_id&TYPEK=all&isnew=false&co_id={c}&year={y}'.encode()
    return urllib.request.urlopen(urllib.request.Request(URL, data=body, headers=HDR), timeout=60).read().decode('utf-8', 'replace')


def push_progress(n):
    if not os.environ.get('GITHUB_ACTIONS') or n % 20: return
    subprocess.run('git add archive/raw/mops_div && git commit -qm "股利分派原始檔進度 %d 份 [skip ci]" && '
                   'for i in 1 2 3; do git pull --rebase -q && git push -q && break; sleep 5; done' % n, shell=True, cwd=ROOT)


def main():
    os.makedirs(OUT, exist_ok=True)
    got = 0
    for c, y in json.load(open(sys.argv[1])):
        f = os.path.join(OUT, f'{c}_{y}.html.gz')
        if os.path.exists(f): continue
        wait = 25
        for attempt in range(6):
            try: t = get(c, y)
            except Exception as e:
                t = ''; print('err', c, y, repr(e)[:80], flush=True)
            if '配股' in t or '查無' in t or '無資料' in t:
                gzip.open(f, 'wt', encoding='utf-8').write(t)
                print('got', c, y, flush=True); got += 1; push_progress(got)
                break
            wait = min(wait * 2, 300); time.sleep(wait)
        time.sleep(25)
    print('done', flush=True)


if __name__ == '__main__':
    main()
