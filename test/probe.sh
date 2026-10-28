#!/bin/bash
# 權值高價股歷史延伸：各來源最早可用日期測試
: > test/pref_probe.txt
probe() {
  curl -sS -m 90 -A "Mozilla/5.0" -o q.json -w "%{http_code}" "$1" > code.txt
  echo "== $1 http=$(cat code.txt) bytes=$(wc -c < q.json)" >> test/pref_probe.txt
  python3 - >> test/pref_probe.txt <<'PY'
import json
try:
    d=json.load(open('q.json'))
    print('stat', d.get('stat'), 'keys', list(d)[:8])
    for t in (d.get('tables') or [])[:12]:
        print(' table', t.get('title'), (t.get('fields') or [])[:10], len(t.get('data') or []))
    if 'fields' in d: print(' fields', d['fields'][:8], len(d.get('data') or []), (d.get('data') or [[]])[0][:6])
    if 'aaData' in d: print(' aaData', len(d['aaData']), d['aaData'][0][:6] if d['aaData'] else '')
except Exception as e: print('ERR', e, open('q.json',encoding='utf-8',errors='replace').read()[:300])
PY
  sleep 6
}
T=https://www.twse.com.tw/rwd/zh
for d in 2007/07/02 2008/01/02 2008/07/01 2009/01/05 2009/07/01; do probe "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=${d//\//%2F}&type=EW&response=json"; done
for d in 96/01/02 93/05/10 99/01/04; do probe "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&d=$d&se=EW"; done
probe "$T/TAIEX/MI_5MINS_HIST?date=20040201&response=json"
probe "$T/afterTrading/FMTQIK?date=20040201&response=json"
