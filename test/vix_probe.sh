#!/bin/bash
# 臺指 VIX 官方資料來源測試 2（Emit 2026-11-06）：期交所即時與歷史檔
O=test/vix_probe.txt; : > $O
UA="Mozilla/5.0 (sector-tracker)"
get(){ curl -sS -m 60 -A "$UA" -o q.bin -w "%{http_code} %{content_type}" "$@" > code.txt 2>err.txt; echo "== $* -> $(cat code.txt) bytes=$(wc -c < q.bin) $(cat err.txt)" >> $O; if iconv -f utf-8 -t utf-8 q.bin >/dev/null 2>&1; then head -c 1500 q.bin; else iconv -f big5 -t utf-8 -c q.bin | head -c 1500; fi >> $O; echo >> $O; sleep 3; }
get -X POST -H 'Content-Type: application/json' -d '{}' https://mis.taifex.com.tw/futures/api/getQuoteListVIX
B=https://www.taifex.com.tw
get "$B/file/taifex/Dailydownload/vix/log2data/202608new.txt"
get "$B/file/taifex/Dailydownload/vix/log2data/202607new.txt"
get "$B/cht/7/getVixData?filesname=20261105"
