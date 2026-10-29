"""權值與高價股分頁：市場狀態（非常態判定）改變時推 LINE。只推觀察訊息，不含買賣建議。
需要 LINE_CHANNEL_ACCESS_TOKEN、LINE_USER_ID；沒有就只印出。"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify import push  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = {-1: '下跌瘋狂', 1: '上漲瘋狂', 2: '資金集中炒作', 0: '常態'}


def main():
    w = json.load(open(os.path.join(ROOT, 'docs', 'wh.json'), encoding='utf-8'))
    e, d = w['ext'], w['dates']
    s0, s1 = e['state'][-2], e['state'][-1]
    if s0 == s1:
        print(d[-1], '市場狀態未改變：', NAME[s1]); return
    sc = lambda v: '—' if v is None else f'{v * 100:.0f}'
    tx = w['taiex'][-1]
    txl = f"加權指數 {tx:,.0f}\n" if tx else ''
    msg = (f"【權值高價股・市場狀態】{d[-1][:4]}-{d[-1][4:6]}-{d[-1][6:]}\n"
           f"{NAME[s0]} → {NAME[s1]}\n"
           f"下跌分數 {sc(e['down'][-1])}（進入85）／上漲分數 {sc(e['up'][-1])}（進入87）／資金集中 {sc(e['conc'][-1])}（進入98.5）\n"
           + txl + "只供觀察，不是交易訊號。\nhttps://ed123698745ed-oss.github.io/sector-tracker/wh.html")
    print(msg); push(msg)


if __name__ == '__main__':
    main()
