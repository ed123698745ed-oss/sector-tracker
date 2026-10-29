#!/bin/bash
# 除權息計算結果表「詳細資料」測試（取配股率，含已下市公司）
: > test/pref_probe.txt
for q in "STK_NO=2311&T1=20100727" "STK_NO=2888&T1=20130910" "STK_NO=6505&T1=20090707" "STK_NO=2330&T1=20090715"; do
  for u in "https://www.twse.com.tw/rwd/zh/exRight/TWT49UDetail?$q&response=json" "https://www.twse.com.tw/exchangeReport/TWT49UDetail?$q&response=json"; do
    curl -sS -m 60 -A "Mozilla/5.0" -o q.json -w "%{http_code}" "$u" > code.txt
    echo "== $u http=$(cat code.txt) bytes=$(wc -c < q.json)" >> test/pref_probe.txt
    head -c 1500 q.json >> test/pref_probe.txt; echo >> test/pref_probe.txt
    sleep 6
  done
done
