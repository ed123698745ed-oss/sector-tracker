#!/bin/bash
for u in "fund/MI_QFIIS?date=20151231&selectType=ALLBUT0999&response=json" "fund/MI_QFIIS?date=20180330&selectType=ALLBUT0999&response=json"; do
  curl -sS -m 90 -A "Mozilla/5.0" -o q.json -w "%{http_code}" "https://www.twse.com.tw/rwd/zh/$u" > code.txt
  echo "== $u http=$(cat code.txt) bytes=$(wc -c < q.json)" >> test/pref_probe.txt
  python3 - >> test/pref_probe.txt <<'PY'
import json
try:
    d=json.load(open('q.json')); print(d.get('stat'), d.get('fields'), len(d.get('data') or []))
    for r in d.get('data') or []:
        if r[0].strip() in ('2311','2325','2888','2823','3474','2330','2881','2809'): print(r[:6])
except Exception as e: print('ERR', e, open('q.json',encoding='utf-8',errors='replace').read()[:200])
PY
  sleep 10
done
