"""抓「決定分派股息及紅利或其他利益之基準日公告」（公開資訊觀測站 t108sb19 列表、t108sb22 內容），
補齊股利分派情形(t05st09)查無或驗證不過的權息事件配股率。
用法：python3 fetch_div_notice.py <targets.json>   targets=[[代號, 除權息交易日YYYYMMDD], ...]
原始檔存 archive/raw/mops_div_notice/<代號>_<公告日>_<序號>.html.gz（列表另存 <代號>_<民國年>_list.html.gz）。
"""
import gzip, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'archive', 'raw', 'mops_div_notice')
BASE = 'https://mopsov.twse.com.tw/mops/web/'


def post(ep, body):
    req = urllib.request.Request(BASE + 'ajax_' + ep, data=body.encode(),
                                 headers={'User-Agent': 'Mozilla/5.0', 'Referer': BASE + 't108sb19'})
    return urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')


def retry(fn, ok):
    wait = 25
    for _ in range(6):
        try:
            t = fn()
            if ok(t): return t
        except Exception as e:
            print('err', repr(e)[:80], flush=True)
        time.sleep(wait); wait = min(wait * 2, 300)
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    for c, ds in json.load(open(sys.argv[1])):
        y = int(ds[:4]) - 1911
        lf = os.path.join(OUT, f'{c}_{y}_list.html.gz')
        if os.path.exists(lf):
            lst = gzip.open(lf, 'rt', encoding='utf-8').read()
        else:
            lst = retry(lambda: post('t108sb19', f'step=1&firstin=1&off=1&queryName=co_id&inpuType=co_id&TYPEK=all&isnew=false&co_id={c}&year={y}'),
                        lambda t: '公告日期' in t or '查無' in t)
            if lst is None: print('list fail', c, y, flush=True); continue
            gzip.open(lf, 'wt', encoding='utf-8').write(lst)
        typek = (re.search(r"name='TYPEK' value='(\w+)'", lst) or re.search(r'name=.TYPEK. value=.(\w+)', lst))
        typek = typek[1] if typek else 'sii'
        for d1, seq in re.findall(r'DATE1\.value="(\d{8})";[^;]*SEQ_NO\.value="(\d+)"', lst):
            f = os.path.join(OUT, f'{c}_{d1}_{seq}.html.gz')
            if os.path.exists(f): continue
            t = retry(lambda: post('t108sb22', f'firstin=true&colorchg=&TYPEK={typek}&isnew=false&id=&DATE1={d1}&SEQ_NO={seq}&COMP={c}&kind=&SKIND=G&step=2'),
                      lambda t: '公告序號' in t)
            if t: gzip.open(f, 'wt', encoding='utf-8').write(t); print('got', c, d1, seq, flush=True)
            time.sleep(20)
        time.sleep(20)
    print('done', flush=True)


if __name__ == '__main__':
    main()
