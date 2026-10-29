"""抓證交所「除權除息計算結果表」詳細資料（TWT49UDetail）：每股現金股利、每千股無償配股。
用於觀測站股利分派情形查不到（多為已下市、合併公司）的權息事件配股率。
用法：python3 fetch_exdetail.py <targets.json>  targets=[[代號, 除權息交易日YYYYMMDD], ...]
原始檔存 archive/raw/twse_exdetail/<代號>_<日期>.json；已存在者略過。
"""
import json, os, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'archive', 'raw', 'twse_exdetail')


def main():
    os.makedirs(OUT, exist_ok=True)
    for c, ds in json.load(open(sys.argv[1])):
        f = os.path.join(OUT, f'{c}_{ds}.json')
        if os.path.exists(f): continue
        u = f'https://www.twse.com.tw/rwd/zh/exRight/TWT49UDetail?STK_NO={c}&T1={ds}&response=json'
        for wait in (10, 30, 90, 180):
            try:
                b = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60).read()
                j = json.loads(b)
                if j.get('data'):
                    open(f, 'wb').write(b); print('got', c, ds, flush=True); break
                print('empty', c, ds, j.get('stat'), flush=True); break
            except Exception as e:
                print('err', c, ds, repr(e)[:80], flush=True); time.sleep(wait)
        time.sleep(5)


if __name__ == '__main__':
    main()
