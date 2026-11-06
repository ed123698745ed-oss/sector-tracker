"""一次性：把財經M平方 46328「台灣-台指選擇權波動指數[VIXTWN]」歷史收盤併入 data/vix_daily.json（Ed 2026-11-06 指示）。

原始檔：archive/raw/macromicro_vix/46328_20261106.txt（Emit 由 Ed 的 Chrome 開圖表頁讀取 Highcharts 序列原樣保存，2016-11-25 起）。
處理：
  - 只收 docs/wh.json 的交易日（M平方在休市日沿用前值，共 117 筆非交易日剔除）。
  - 期交所每月檔已有的日期以期交所為準，不覆蓋（2026/08～11 重疊 64 日逐日相同）。
  - 剔除孤立異常值：2017-01-12 23.02（前後日 11.46、11.54），不補值。
  - M平方缺的交易日（2017-02-18、06-03、09-30 補班日，2020-10-13）維持無資料，不補。
標記 src='mm'。重跑結果相同（冪等）。
"""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'archive', 'raw', 'macromicro_vix', '46328_20261106.txt')
EXCLUDE = {'20170112': '孤立異常值 23.02（前後日 11.46、11.54）'}

def main():
    mm = {}
    for line in open(RAW, encoding='utf-8'):
        if line.startswith('#'):
            continue
        for x in line.split():
            d, v = x.split(':'); mm['20' + d] = float(v)
    td = set(json.load(open(os.path.join(ROOT, 'docs', 'wh.json'), encoding='utf-8'))['dates'])
    p = os.path.join(ROOT, 'data', 'vix_daily.json')
    daily = json.load(open(p, encoding='utf-8'))
    add = same = diff = 0
    for d, v in sorted(mm.items()):
        if d not in td or d in EXCLUDE:
            continue
        r = daily.get(d)
        if r and r.get('src') != 'mm':
            same += abs(r['c'] - v) <= 0.005; diff += abs(r['c'] - v) > 0.005
            continue
        daily[d] = {'c': v, 'src': 'mm'}; add += 1
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(dict(sorted(daily.items())), f, ensure_ascii=False, indent=0)
    print(f'M平方 {len(mm)} 筆；併入交易日 {add}；與期交所重疊相同 {same}、不同 {diff}；剔除 {list(EXCLUDE)}')

if __name__ == '__main__':
    main()
