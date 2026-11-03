"""GitHub Actions 工作失敗時推 LINE（2026-11-03 檢驗報告第 10 項：每日工作失敗要有通知，不可靜默）。
用法：python3 notify_failure.py <工作名稱> <執行紀錄網址>；沒設定 LINE secrets 就只印出。只通知，不含買賣建議。
"""
import datetime, sys

from notify import push

if __name__ == '__main__':
    name = sys.argv[1] if len(sys.argv) > 1 else '排程工作'
    url = sys.argv[2] if len(sys.argv) > 2 else ''
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%m/%d %H:%M')
    msg = f'【sector-tracker・排程失敗】{now}\n{name} 執行失敗，請 Emit 檢查。\n{url}'
    print(msg)
    push(msg)
