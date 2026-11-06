"""臺指選擇權波動率指數（臺指 VIX）：抓取、保存、產出 docs/vix.json。只供觀察，不是交易訊號。

資料來源（皆為臺灣期貨交易所，2026-11-06 由 GitHub Actions 實測可取得）：
  - 每日收盤：期交所「臺指選擇權波動率指數下載」每月檔
      https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/YYYYMMnew.txt
    欄位：交易日期、時間、臺指選擇權波動率指數（13:45 收盤值）、收盤前 1 分鐘平均指數。
    期交所只公開最近約 4 個月（2026-11-06 實測：2026/08 起；2026/07 已下架）。
  - 盤中即時：期交所行情資訊網 https://mis.taifex.com.tw/futures/api/getQuoteListVIX（POST {}）
    欄位：CLastPrice、COpenPrice、CHighPrice、CLowPrice、CRefPrice（前一日收盤）、CDate、CTime。
    每 15 秒更新，揭示時間 09:00～13:45。

保存：
  - archive/raw/taifex_vix/YYYYMMnew.txt  每月檔原始內容（每次覆蓋為最新版）
  - data/vix_daily.json  {日期: {c 收盤, c1m 收盤前1分鐘平均, o/h/l 當日開高低（取自盤後即時報價，可能缺）}}
    已存在的日期不刪除：期交所下架舊月份後，網站仍保有本站抓過的歷史。
  - docs/vix.json  網頁用

防錯（對照《00_Emit事故檢討與建置防錯清單》）：
  - 日期以資料本身的交易日期為準（B／A1），即時報價以 CDate 為準。
  - 2xx 也要能解析：每月檔須有表頭且資料列為 8 碼日期＋數字，否則視為失敗、不覆蓋既有資料（B 2xx）。
  - 外部抓取逾時、連線錯誤、5xx 退讓重試（D4）。
  - 某月抓不到不影響其他月份；全部失敗才以非 0 結束（B 多來源分開成敗）。

  python3 scripts/vix.py daily      盤後：抓最近 4 個月每月檔＋盤後即時（取開高低），更新 data／docs
  python3 scripts/vix.py live       只抓一次即時報價並印出（測試用）
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPE = datetime.timezone(datetime.timedelta(hours=8))
MONTH_URL = 'https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{ym}new.txt'
LIVE_URL = 'https://mis.taifex.com.tw/futures/api/getQuoteListVIX'
RAW_DIR = os.path.join(ROOT, 'archive', 'raw', 'taifex_vix')
DAILY = os.path.join(ROOT, 'data', 'vix_daily.json')
OUT = os.path.join(ROOT, 'docs', 'vix.json')
UA = 'Mozilla/5.0 (sector-tracker; Ai Bot Team Emit)'
SOURCE = '臺灣期貨交易所 臺指選擇權波動率指數（每月下載檔、行情資訊網 mis.taifex.com.tw）'


def _req(url, data=None, tries=4, timeout=30):
    last = None
    for k in range(tries):
        try:
            r = urllib.request.Request(url, data=data, headers={'User-Agent': UA, **(
                {'Content-Type': 'application/json'} if data is not None else {})})
            with urllib.request.urlopen(r, timeout=timeout) as f:
                return f.status, f.headers.get('Content-Type', ''), f.read()
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if e.code < 500 and e.code != 429:
                return e.code, '', b''
        except Exception as e:  # 逾時、連線錯誤
            last = str(e)[:120]
        time.sleep(3 * (k + 1))
    raise RuntimeError(f'{url} 重試 {tries} 次仍失敗：{last}')


def num(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def parse_month(raw):
    """回傳 {日期: (收盤, 收盤前1分鐘平均)}；格式不符丟 ValueError。"""
    for enc in ('utf-8', 'big5', 'cp950'):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('無法解碼')
    if '臺指選擇權波動率指數' not in txt:
        raise ValueError('沒有預期表頭：' + txt[:200].replace('\n', ' '))
    rows = {}
    for line in txt.splitlines():
        p = line.split()
        if len(p) >= 3 and re.fullmatch(r'20\d{6}', p[0]):
            c = num(p[2])
            if c is None:
                raise ValueError('收盤值非數字：' + line)
            rows[p[0]] = (c, num(p[3]) if len(p) >= 4 else None)
    return rows


def fetch_month(ym):
    st, ct, raw = _req(MONTH_URL.format(ym=ym))
    if st != 200 or not raw:
        return None, f'{ym}: HTTP {st}（期交所未提供或已下架）'
    rows = parse_month(raw)
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(os.path.join(RAW_DIR, f'{ym}new.txt'), 'wb') as f:
        f.write(raw)
    return rows, f'{ym}: {len(rows)} 日'


def fetch_live():
    """期交所即時臺指 VIX。回傳 dict 或丟例外。"""
    st, ct, raw = _req(LIVE_URL, data=b'{}', tries=3, timeout=20)
    if st != 200:
        raise RuntimeError(f'HTTP {st}')
    try:
        j = json.loads(raw.decode('utf-8'))
        q = j['RtData']['QuoteList'][0]
    except Exception:
        raise RuntimeError(f'回應格式不符 ct={ct} body={raw[:200]!r}')
    last, ref = num(q.get('CLastPrice')), num(q.get('CRefPrice'))
    d, t = q.get('CDate') or '', q.get('CTime') or ''
    if last is None or not re.fullmatch(r'20\d{6}', d):
        raise RuntimeError(f'即時報價缺值：{q}')
    return {'last': last, 'ref': ref, 'open': num(q.get('COpenPrice')), 'high': num(q.get('CHighPrice')),
            'low': num(q.get('CLowPrice')), 'date': d, 'time': t[:2] + ':' + t[2:4] + ':' + t[4:6] if len(t) >= 6 else t}


def months_back(n, today=None):
    d = (today or datetime.datetime.now(TPE)).date().replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.strftime('%Y%m'))
        d = (d - datetime.timedelta(days=1)).replace(day=1)
    return out


def load_daily():
    return json.load(open(DAILY, encoding='utf-8')) if os.path.exists(DAILY) else {}


def build(daily):
    ds = sorted(daily)
    out = {'source': SOURCE, 'updated': datetime.datetime.now(TPE).strftime('%Y-%m-%d %H:%M'),
           'dates': ds, 'c': [daily[d].get('c') for d in ds], 'o': [daily[d].get('o') for d in ds],
           'h': [daily[d].get('h') for d in ds], 'l': [daily[d].get('l') for d in ds]}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    return out


def daily_update():
    daily, logs, ok = load_daily(), [], 0
    for ym in months_back(4):
        try:
            rows, msg = fetch_month(ym)
        except Exception as e:
            rows, msg = None, f'{ym}: 失敗 {str(e)[:160]}'
        logs.append(msg)
        if rows is None:
            continue
        ok += 1
        for d, (c, c1m) in rows.items():
            r = daily.setdefault(d, {})
            if r.get('c') is not None and abs(r['c'] - c) > 0.005:
                logs.append(f'  {d} 收盤由 {r["c"]} 更正為 {c}（每月檔為準）')
            r['c'], r['c1m'] = c, c1m
    # 盤後即時報價補當日開高低（每月檔只有收盤）；收盤 13:45 後才採用
    try:
        lv = fetch_live()
        logs.append(f"live {lv['date']} {lv['time']} last {lv['last']} o/h/l {lv['open']}/{lv['high']}/{lv['low']}")
        if lv['time'] >= '13:45:00':
            r = daily.setdefault(lv['date'], {})
            r.update({'o': lv['open'], 'h': lv['high'], 'l': lv['low']})
            if r.get('c') is None:
                r['c'] = lv['last']   # 每月檔尚未更新時先用即時收盤，之後由每月檔覆蓋
                r['src'] = 'mis'
            elif abs(r['c'] - lv['last']) > 0.005:
                logs.append(f"  ⚠ {lv['date']} 每月檔收盤 {r['c']} ≠ 即時收盤 {lv['last']}")
    except Exception as e:
        logs.append(f'live 失敗：{str(e)[:160]}')
    for d, r in daily.items():   # 每月檔已收錄的日期去掉暫用標記
        if r.get('c1m') is not None:
            r.pop('src', None)
    os.makedirs(os.path.dirname(DAILY), exist_ok=True)
    with open(DAILY, 'w', encoding='utf-8') as f:
        json.dump(dict(sorted(daily.items())), f, ensure_ascii=False, indent=0)
    out = build(daily)
    logs.append(f"vix.json {len(out['dates'])} 日 {out['dates'][0] if out['dates'] else '—'}～{out['dates'][-1] if out['dates'] else '—'}")
    print('\n'.join(logs))
    return 0 if ok else 1


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'daily'
    if cmd == 'live':
        print(fetch_live())
        sys.exit(0)
    sys.exit(daily_update())
