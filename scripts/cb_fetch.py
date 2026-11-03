"""可轉債追蹤：抓櫃買 RSta0113 每日檔，原樣 gzip 存 archive/raw/tpex_cb。

用法：
  python3 scripts/cb_fetch.py            # 從最後一份已存檔的次日抓到今天（台北日期，最多回看 15 天）
  python3 scripts/cb_fetch.py 20261103   # 只抓指定日
  python3 scripts/cb_fetch.py --import 目錄   # 匯入既有下載的 RSta0113.YYYYMMDD-C.csv（一次性回補用）

防錯（Emit 防錯清單）：
  A1 資料日以檔內 DATADATE 為準，與要求日期不同就不存
  A2 data/closed.txt 的臨時休市日不抓；非交易日櫃買回 302／404，不存檔
  B1 內容檢查：TITLE 開頭、有 HEADER 與「合計」列；有參價的檔數為 0、或全無等價成交（春節前只交割不交易日）不存
  B2 有參價檔數低於前一份存檔的 90% 不存，exit 2（排程會失敗，網頁維持上一日並顯示資料日）
  B 2xx 也驗內容；失敗 log status、Content-Type、前 200 字
"""
import datetime as dt, gzip, os, sys, time
import requests
from cb_common import url, arch_path, archived_dates, closed_dates, parse, load, ParseError

TPE = dt.timezone(dt.timedelta(hours=8))
UA = {'User-Agent': 'sector-tracker (observation site)'}


def n_ref(rows):
    return sum(1 for r in rows if r['ref'] and r['ref'] > 0)


def prev_count(d):
    ds = [x for x in archived_dates() if x < d]
    for x in reversed(ds[-5:]):
        try:
            return x, n_ref(load(x)[1])
        except Exception:
            continue
    return None, None


def save(d, raw, rows):
    """通過檢查才存。回傳 'saved' 或錯誤字串。"""
    n = n_ref(rows)
    if n == 0:
        return f'{d} 有參價的檔數為 0（空白檔），不存'
    if not any(r['close'] for r in rows):
        return f'{d} 沒有任何等價成交（春節前只交割不交易日等），視為非交易日，不存'
    pd_, pn = prev_count(d)
    if pn and n < pn * 0.9:
        return f'{d} 有參價 {n} 檔，低於前一份 {pd_} 的 {pn} 檔 90%，不存（防錯 B2）'
    p = arch_path(d)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as fo, gzip.GzipFile(fileobj=fo, mode='wb', mtime=0) as f:
        f.write(raw)
    return 'saved'


def fetch(d, s):
    for k in range(4):
        try:
            r = s.get(url(d), timeout=30, allow_redirects=False, headers=UA)
        except requests.RequestException as e:
            print(f'{d} 連線錯誤 {type(e).__name__}，第 {k + 1} 次')
            time.sleep(3 + 5 * k)
            continue
        if r.status_code in (301, 302, 404):
            return None, f'{d} 尚未公布或非交易日（HTTP {r.status_code}）'
        if r.status_code != 200:
            print(f'{d} HTTP {r.status_code}，第 {k + 1} 次')
            time.sleep(3 + 5 * k)
            continue
        try:
            fd, rows = parse(r.content)
        except ParseError as e:
            print(f'{d} 內容錯誤：{e}；status={r.status_code} type={r.headers.get("Content-Type")} '
                  f'body={r.content[:200]!r}')
            time.sleep(3 + 5 * k)
            continue
        if fd != d:
            return None, f'{d} 檔內資料日為 {fd}，與要求日期不同，不存（防錯 A1）'
        return (r.content, rows), None
    return None, f'{d} 重試 4 次仍失敗'


def main():
    a = sys.argv[1:]
    if a and a[0] == '--import':
        src = a[1]
        ok = bad = 0
        have = set(archived_dates())
        for f in sorted(os.listdir(src)):
            if not (f.startswith('RSta0113.') and f.endswith('-C.csv')):
                continue
            d = f[9:17]
            if d in have:
                continue
            raw = open(os.path.join(src, f), 'rb').read()
            try:
                fd, rows = parse(raw)
            except ParseError as e:
                print(f'{d} 略過：{e}'); bad += 1; continue
            if fd != d:
                print(f'{d} 略過：檔內日期 {fd}'); bad += 1; continue
            if d in closed_dates():
                print(f'{d} 略過：在 closed.txt'); bad += 1; continue
            res = save(d, raw, rows)
            if res == 'saved':
                ok += 1
            else:
                print(res); bad += 1
        print(f'匯入 {ok} 份，略過 {bad} 份')
        return 0
    today = dt.datetime.now(TPE).date()
    if a:
        targets = [a[0]]
    else:
        last = archived_dates()[-1:] or ['20070101']
        start = max(dt.datetime.strptime(last[0], '%Y%m%d').date() + dt.timedelta(1), today - dt.timedelta(15))
        targets = [(start + dt.timedelta(i)).strftime('%Y%m%d') for i in range((today - start).days + 1)]
        targets = [d for d in targets if dt.datetime.strptime(d, '%Y%m%d').weekday() < 5]
    closed = closed_dates()
    s = requests.Session()
    saved, rc = [], 0
    for d in targets:
        if d in closed:
            print(f'{d} 在 closed.txt（臨時休市），略過'); continue
        got, err = fetch(d, s)
        if err:
            print(err)
            if '不存' in err or '仍失敗' in err:
                rc = 2
            continue
        res = save(d, *got)
        if res == 'saved':
            print(f'{d} 已存：{n_ref(got[1])} 檔有參價，{sum(1 for r in got[1] if r["close"])} 檔有等價成交')
            saved.append(d)
        else:
            print(res); rc = 2
    out = os.environ.get('GITHUB_OUTPUT')
    if out:
        with open(out, 'a') as f:
            f.write(f'saved={" ".join(saved)}\n')
    return rc


if __name__ == '__main__':
    sys.exit(main())
