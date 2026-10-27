#!/bin/bash
i=0
for ep in t108sb19 t05st09_new; do
 for body in "step=1&firstin=1&off=1&queryName=co_id&inpuType=co_id&TYPEK=all&isnew=false&co_id=1519&year=113" "step=1&firstin=1&off=1&TYPEK=sii&co_id=1519&year=113"; do
  i=$((i+1))
  code=$(curl -sS -m 90 -A "Mozilla/5.0" -e "https://mopsov.twse.com.tw/mops/web/$ep" -o r$i.html -w "%{http_code}" -d "$body" https://mopsov.twse.com.tw/mops/web/ajax_$ep || echo ERR)
  echo "$(date -u +%FT%TZ) $ep v$i http=$code bytes=$(wc -c < r$i.html) 配股=$(grep -c 配股 r$i.html) 查無=$(grep -c 查無 r$i.html) 安全性=$(grep -c 安全性 r$i.html) | $body" >> test/pref_probe.txt
  sleep 20
 done
done
best=$(ls -S r*.html | head -1)
echo "BEST $best" >> test/pref_probe.txt
python3 - "$best" >> test/pref_probe.txt <<'PY'
import re,sys
t=open(sys.argv[1],encoding='utf-8',errors='replace').read()
s=re.sub(r'\s+',' ',re.sub('<[^>]+>','|',t)); s=re.sub(r'(\| ?)+','|',s)
i=s.find('配股'); print('BODY', s[max(0,i-1500):i+1500])
PY
