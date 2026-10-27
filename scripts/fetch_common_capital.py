"""抓有特別股公司的個別資產負債表（公開資訊觀測站 t164sb03），取「普通股股本」，供上市市值扣除特別股。
對象：曾進上市市值前 50、且有上市特別股的公司，期間為其特別股掛牌期間（含前一季）。
中鋼特別股占股本約 0.24%，不抓。
用法：python3 fetch_common_capital.py <targets.json>   targets=[[代號, 民國年, 季], ...]
原始檔存 archive/raw/mops_bs_co/<代號>_<年>_<季>.html.gz；已存在者略過。觀測站會擋頻繁請求，每次間隔 25 秒，被擋則退避。
"""
import gzip, json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'archive', 'raw', 'mops_bs_co')
URL = 'https://mopsov.twse.com.tw/mops/web/ajax_t164sb03'
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mopsov.twse.com.tw/mops/web/t164sb03'}


def get(c, y, q):
    body = f'step=1&firstin=1&off=1&queryName=co_id&inpuType=co_id&TYPEK=all&isnew=false&co_id={c}&year={y}&season={q:02d}'.encode()
    return urllib.request.urlopen(urllib.request.Request(URL, data=body, headers=HDR), timeout=60).read().decode('utf-8', 'replace')


def push_progress(n):
    """在 GitHub Actions 中每抓到 10 份就提交一次，進度可從 repo 即時看到"""
    if not os.environ.get('GITHUB_ACTIONS') or n % 10: return
    sh = lambda c: subprocess.run(c, shell=True, cwd=ROOT)
    sh('git add archive/raw/mops_bs_co && git commit -qm "特別股原始檔進度 %d 份 [skip ci]" && '
       'for i in 1 2 3; do git pull --rebase -q && git push -q && break; sleep 5; done' % n)


def main():
    os.makedirs(OUT, exist_ok=True)
    tg = json.load(open(sys.argv[1]))
    got = 0
    for c, y, q in tg:
        if c == '2002':
            continue
        f = os.path.join(OUT, f'{c}_{y}_{q:02d}.html.gz')
        if os.path.exists(f):
            continue
        wait = 25
        for attempt in range(8):
            try:
                t = get(c, y, q)
            except Exception as e:
                t = ''
                print('err', c, y, q, repr(e)[:80], flush=True)
            if '普通股股本' in t or '股本合計' in t:
                gzip.open(f, 'wt', encoding='utf-8').write(t)
                print('got', c, y, q, flush=True)
                got += 1; push_progress(got)
                break
            if '查無' in t or '不存在' in t:
                print('none', c, y, q, flush=True)
                break
            wait = min(wait * 2, 300)
            time.sleep(wait)
        time.sleep(25)
    print('done', flush=True)


if __name__ == '__main__':
    main()
