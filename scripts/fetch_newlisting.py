"""抓證交所「最近上市公司」各年度清單（含股票上市買賣日期、備註），供判定初次上市首五日無漲跌幅限制。
另抓櫃買上櫃公司基本資料（openapi mopsfin_t187ap03_O，含現存公司上櫃日期）。
原始檔存 archive/raw/twse_newlisting/<西元年>.json、archive/raw/tpex_companies/<抓取日>.json
"""
import json, os, sys, time, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get(u):
    for wait in (10, 30, 90):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=90).read()
        except Exception as e:
            print('err', u, repr(e)[:80], flush=True); time.sleep(wait)
    raise SystemExit('抓取失敗 ' + u)


def main():
    out = os.path.join(ROOT, 'archive', 'raw', 'twse_newlisting'); os.makedirs(out, exist_ok=True)
    this = datetime.date.today().year
    for y in range(2004, this + 1):
        f = os.path.join(out, f'{y}.json')
        if os.path.exists(f) and y < this: continue
        b = get(f'https://www.twse.com.tw/rwd/zh/company/newlisting?date={y}&response=json')
        j = json.loads(b)
        if str(j.get('stat')).upper() != 'OK': raise SystemExit(f'{y} {j.get("stat")}')
        open(f, 'wb').write(b); print(y, len(j.get('data') or []), flush=True); time.sleep(5)
    out2 = os.path.join(ROOT, 'archive', 'raw', 'tpex_companies'); os.makedirs(out2, exist_ok=True)
    b = get('https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O')
    open(os.path.join(out2, datetime.date.today().strftime('%Y%m%d') + '.json'), 'wb').write(b)


if __name__ == '__main__':
    main()
