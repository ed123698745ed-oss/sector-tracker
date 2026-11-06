#!/bin/bash
# 臺指 VIX 資料來源測試（Emit 2026-11-06）
O=test/vix_probe.txt; : > $O
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
get(){ curl -sS -m 60 -A "$UA" -o q.bin -w "%{http_code} %{content_type}" "$@" > code.txt 2>err.txt; echo "== $* -> $(cat code.txt) bytes=$(wc -c < q.bin) $(cat err.txt)" >> $O; iconv -f big5 -t utf-8 q.bin 2>/dev/null | head -c 900 >> $O || head -c 900 q.bin >> $O; echo >> $O; sleep 3; }
B=https://www.taifex.com.tw
for p in cht/7/vixMinNew cht/7/vixMin3MNew cht/7/vixDaily3MNew cht/7/vixDailyNew; do
  curl -sS -m 60 -A "$UA" "$B/$p" -o page.html; echo "== PAGE $p links:" >> $O
  grep -oiE '(href|onclick)="[^"]*"' page.html | grep -iE 'vix|\.txt|download|file' | sort -u | head -40 >> $O
  grep -oiE "[\"'][^\"']*vix[^\"']*\.(txt|csv|zip)[\"']" page.html | sort -u | head -20 >> $O
  grep -oiE "Dailydownload[^\"' ]*" page.html | sort -u | head -20 >> $O
done
for f in 202610new.txt 20261105new.txt 202610.txt 200612new.txt 201001new.txt 202001new.txt 202510new.txt; do get "$B/file/taifex/Dailydownload/vix/log2data/$f"; done
get "$B/file/taifex/Dailydownload/vix/log2data/"
# 即時
get -X POST -H 'Content-Type: application/json' -d '{}' https://mis.taifex.com.tw/futures/api/getQuoteListVIX
get -X POST -H 'Content-Type: application/json' -d '{"SymbolID":["TAIWANVIX-S"]}' https://mis.taifex.com.tw/futures/api/getQuoteDetail
get -X POST -H 'Content-Type: application/json' -d '{"MarketType":"0","SymbolType":"F","KindID":"1","CID":"TXF","ExpireMonth":"","RowSize":"全部","PageNo":"","SortColumn":"","AscDesc":"A"}' https://mis.taifex.com.tw/futures/api/getQuoteList
curl -sS -m 60 -A "$UA" https://mis.taifex.com.tw/futures/VolatilityQuotes/ -o mis.html; echo "== MIS page bytes=$(wc -c < mis.html)" >> $O
grep -oE 'src="[^"]*\.js"' mis.html | head >> $O
for js in $(grep -oE 'src="[^"]*\.js"' mis.html | sed 's/src="//;s/"//' | head -8); do
  case $js in http*) u=$js;; /*) u=https://mis.taifex.com.tw$js;; *) u=https://mis.taifex.com.tw/futures/VolatilityQuotes/$js;; esac
  curl -sS -m 60 -A "$UA" "$u" -o a.js; echo "-- $u" >> $O; grep -oE '"?/?(futures/)?api/[A-Za-z]+' a.js | sort -u | head -40 >> $O; grep -oiE '.{60}VIX.{80}' a.js | head -15 >> $O
done
