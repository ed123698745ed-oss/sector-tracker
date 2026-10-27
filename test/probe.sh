#!/bin/bash
u=https://mopsov.twse.com.tw/mops/web/ajax_t05st09
i=0
for body in "step=1&firstin=1&off=1&queryName=co_id&inpuType=co_id&TYPEK=all&isnew=false&co_id=2892&year=110" "step=2&firstin=1&off=1&queryName=co_id&inpuType=co_id&TYPEK=all&isnew=false&co_id=2892&year=110"; do
  i=$((i+1))
  code=$(curl -sS -m 90 -A "Mozilla/5.0" -e "https://mopsov.twse.com.tw/mops/web/t05st09" -o r$i.html -w "%{http_code}" -d "$body" $u || echo ERR)
  echo "$(date -u +%FT%TZ) t05st09 v$i http=$code bytes=$(wc -c < r$i.html) 配股=$(grep -c 配股 r$i.html) 安全性=$(grep -c 安全性 r$i.html) | $body" >> test/pref_probe.txt
  sleep 20
done
best=$(ls -S r*.html | head -1)
python3 - "$best" >> test/pref_probe.txt <<'PY'
import re,sys
t=open(sys.argv[1],encoding='utf-8',errors='replace').read()
s=re.sub(r'\s+',' ',re.sub('<[^>]+>','|',t)); s=re.sub(r'(\| ?)+','|',s)
i=s.find('股東會'); print('BODY', s[max(0,i-200):i+2500])
PY
