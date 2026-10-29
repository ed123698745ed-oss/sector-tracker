#!/bin/bash
# 初次上市／上櫃日期資料來源測試
: > test/pref_probe.txt
for u in "https://www.twse.com.tw/rwd/zh/company/newlisting?response=json" \
 "https://www.twse.com.tw/rwd/zh/company/newlisting?date=2012&response=json" \
 "https://www.twse.com.tw/rwd/zh/company/applylisting?response=json" \
 "https://openapi.twse.com.tw/v1/opendata/t187ap03_L" \
 "https://www.twse.com.tw/rwd/zh/company/suspendListing?response=json" \
 "https://www.tpex.org.tw/www/zh-tw/company/newlisting?response=json" \
 "https://www.tpex.org.tw/www/zh-tw/listed/newListing?response=json" \
 "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis" \
 "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O" ; do
  curl -sS -m 60 -A "Mozilla/5.0" -o q.json -w "%{http_code}" "$u" > code.txt
  echo "== $u http=$(cat code.txt) bytes=$(wc -c < q.json)" >> test/pref_probe.txt
  head -c 1200 q.json >> test/pref_probe.txt; echo >> test/pref_probe.txt
  sleep 5
done
