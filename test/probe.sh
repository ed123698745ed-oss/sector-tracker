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
for ds in 20040211 20040510 20061229 20070102 20100104; do probe "$T/afterTrading/MI_INDEX?date=$ds&type=ALLBUT0999&response=json"; done
for d in 2007/01/02 2006/12/29 2004/05/10 2010/01/04; do probe "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=${d//\//%2F}&type=EW&response=json"; done
for ds in 20040227 20061229 20070131 20091231; do probe "$T/fund/MI_QFIIS?date=$ds&selectType=ALLBUT0999&response=json"; done
for y in 2004 2008 2011; do
  probe "$T/exRight/TWT49U?startDate=${y}0101&endDate=${y}1231&response=json"
  probe "$T/reducation/TWTAUU?startDate=${y}0101&endDate=${y}1231&response=json"
  probe "$T/change/TWTB8U?startDate=${y}0101&endDate=${y}1231&response=json"
done
