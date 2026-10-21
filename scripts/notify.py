"""市場階段警示：資料日當天若階段改變，推 LINE（Messaging API push）。
需要環境變數 LINE_CHANNEL_ACCESS_TOKEN、LINE_USER_ID（GitHub Secrets）；沒有就只印出，不報錯。
只推「觀察」訊息，不含買賣建議。
"""
import json, os, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    data = json.load(open(f'{ROOT}/docs/data.json', encoding='utf-8'))
    alerts = json.load(open(f'{ROOT}/docs/alerts.json', encoding='utf-8'))
    d = data['days'][-1]
    ev = [e for e in alerts['events'] if e['d'] == d['d']]
    if not ev:
        print(d['d'], '階段未改變，不推播'); return
    e = ev[-1]; mp = d['mp']
    msg = (f"【族群網站・市場階段】{d['d'][:4]}-{d['d'][4:6]}-{d['d'][6:]}\n"
           f"{e['from']} → {e['to']}\n"
           f"轉弱 {mp[3]}（今日 {mp[0]}）／站穩月線 {mp[4]}／本週主流 {mp[5]}（上週 {mp[7]}）\n"
           f"只供觀察，不是交易訊號。\nhttps://ed123698745ed-oss.github.io/sector-tracker/")
    print(msg)
    tok, uid = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'), os.environ.get('LINE_USER_ID')
    if not (tok and uid):
        print('未設定 LINE secrets，略過推播'); return
    body = json.dumps({'to': uid, 'messages': [{'type': 'text', 'text': msg}]}).encode()
    req = urllib.request.Request('https://api.line.me/v2/bot/message/push', data=body,
                                 headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {tok}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        print('LINE', r.status)


if __name__ == '__main__':
    main()
