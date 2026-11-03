"""每日更新證交所當年度減資恢復買賣（TWTAUU）、變更面額恢復買賣（TWTB8U）全年表到 archive/raw/twse_events。

融資觀察判斷「前日餘額不連續」是否為股數事件要用這兩張表（margin_build.py 說明第 5 點）；原本只在每月名單更新時重抓，
月中的上市分割要到下個月才認得（2026-11-03 檢驗報告後續）。驗證格式後才覆寫；失敗以非零結束、不動舊檔。
用法：python3 fetch_twse_events.py [YYYY]
"""
import datetime, json, os, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = {'TWTAUU': 'reducation', 'TWTB8U': 'change'}


def get(u):
    for i in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60).read()
        except Exception as e:
            print('retry', i, repr(e)[:80], flush=True)
            time.sleep(15 * (i + 1))
    raise SystemExit(f'抓取失敗：{u}')


def main():
    yy = int(sys.argv[1]) if len(sys.argv) > 1 else datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).year
    for k, ctl in EV.items():
        b = get(f'https://www.twse.com.tw/rwd/zh/{ctl}/{k}?startDate={yy}0101&endDate={yy}1231&response=json')
        j = json.loads(b)
        if j.get('stat') != 'OK' or not j.get('fields') or not isinstance(j.get('data', []), list):
            raise SystemExit(f'{k} {yy} 格式不符：stat={j.get("stat")}')
        fp = os.path.join(ROOT, 'archive', 'raw', 'twse_events', f'{k}_{yy}.json')
        old = json.load(open(fp)) if os.path.exists(fp) else {}
        if len(j.get('data') or []) < len(old.get('data') or []):   # 全年表只會變多：變少視為異常，不覆寫
            raise SystemExit(f'{k} {yy} 筆數 {len(j.get("data") or [])} 少於既有 {len(old.get("data") or [])}，不覆寫')
        open(fp, 'wb').write(b)
        print(k, yy, len(j.get('data') or []), flush=True)
        time.sleep(3)


if __name__ == '__main__':
    main()
