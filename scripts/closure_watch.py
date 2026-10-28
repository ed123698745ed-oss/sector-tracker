"""臨時休市自動偵測（颱風等）：盯證交所最新消息，公告「集中交易市場115年X月X日休市一天」就自動寫入 data/closed.txt。

2026-10-23 颱風臨時休市要靠人工登錄 closed.txt（事故 4）。比照 stock-track 的 closure_watch 改成自動：
  ① 讀證交所最新消息，標題完整符合「集中交易市場115年10月23日休市一天」→ 取出日期
  ② 該日是今天或未來的平日、closed.txt 還沒有 → 寫入，並推 LINE 通知
  ③ 看到「颱風／休市／停止交易」等字眼但格式不符（上午休市、延後開盤…）→ 只推「請人工確認」，不寫檔（同一則只推一次）
closed.txt 會被 continuity（週結算）、backfill（補資料）使用；盤中另有報價日期檢查，休市日本來就不會更新。
DRY_RUN=1：只印不寫、不推。TODAY=YYYY-MM-DD 可指定日期測試。
"""
import datetime as dt, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
CLOSED = f'{ROOT}/data/closed.txt'
SEEN = f'{ROOT}/data/closure_seen.txt'
NEWS = 'https://www.twse.com.tw/rwd/zh/news/newsList?response=json'
TPE = dt.timezone(dt.timedelta(hours=8))
W = '一二三四五六日'
FULL = re.compile(r'集中交易市場(\d{3})年(\d{1,2})月(\d{1,2})日(?:全日)?休市(?:一天|一日)?$')
HINT = re.compile(r'颱風|休市|停止交易|暫停交易|延後開盤|天災')
NOT_MARKET = ('股份有限公司', 'ETF', '受益憑證', '權證', '指數投資證券')  # 個股停止買賣不是市場休市
PARTIAL = ('上午', '下午', '半日', '延後', '恢復', '提前')


def roc(s):
    m = re.match(r'(\d{3})年(\d{1,2})月(\d{1,2})日', s or '')
    return dt.date(int(m[1]) + 1911, int(m[2]), int(m[3])) if m else None


def scan(rows, today, known):
    """rows：newsList 的 data（[序號, 標題, 發布日期, …]）。只看最近 7 天發布的消息。
    回傳 (要自動寫入的 [(日期, 標題)], 要人工確認的 [標題])。"""
    auto, manual = [], []
    for r in rows:
        title, pub = (r[1] or '').strip(), roc(r[2])
        if not pub or (today - pub).days > 7 or pub > today + dt.timedelta(days=1):
            continue
        m = FULL.search(title)
        if m and not any(k in title for k in PARTIAL):
            d = dt.date(int(m[1]) + 1911, int(m[2]), int(m[3]))
            if d >= today and d.weekday() < 5 and d.strftime('%Y%m%d') not in known:
                auto.append((d, title))
            continue
        if HINT.search(title) and not any(k in title for k in NOT_MARKET):
            manual.append(title)
    return sorted(set(auto)), manual


def lines(path):
    return [x.strip() for x in open(path, encoding='utf-8')] if os.path.exists(path) else []


def main():
    import notify
    dry = os.environ.get('DRY_RUN') == '1'
    today = dt.date.fromisoformat(os.environ['TODAY']) if os.environ.get('TODAY') else dt.datetime.now(TPE).date()
    req = urllib.request.Request(NEWS, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.loads(r.read().decode('utf-8')).get('data') or []
    known = set(lines(CLOSED))
    auto, manual = scan(rows, today, known)
    print(f'最新消息 {len(rows)} 則；自動登錄 {len(auto)}、需人工確認 {len(manual)}')
    for d, title in auto:
        msg = (f'【族群網站・臨時休市】證交所公告 {d.month}/{d.day}（{W[d.weekday()]}）集中市場休市\n（{title}）\n'
               f'已自動寫入休市日：當天盤中不更新，週結算會把前一個交易日當週末。')
        print(msg)
        if dry:
            continue
        known.add(d.strftime('%Y%m%d'))
        open(CLOSED, 'w', encoding='utf-8').write('\n'.join(sorted(x for x in known if x)) + '\n')
        notify.push(msg)
    seen = set(lines(SEEN))
    for title in manual:
        if title in seen:
            continue
        msg = f'【族群網站】證交所公告可能影響交易日，請人工確認：\n{title}\n（不是「X月X日休市一天」格式，未自動寫入 closed.txt）'
        print(msg)
        if dry:
            continue
        notify.push(msg)
        with open(SEEN, 'a', encoding='utf-8') as f:
            f.write(title + '\n')


if __name__ == '__main__':
    main()
