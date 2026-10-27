#!/bin/bash
# 連線測試腳本：由 pref_probe.yml 執行，結果寫入 test/pref_probe.txt
u=https://mopsov.twse.com.tw/mops/web/ajax_t05st09_2
i=0
for body in "step=1&firstin=1&off=1&isQuery=Y&TYPEK=sii&year=110&qryType=1" "encodeURIComponent=1&step=1&firstin=1&off=1&isQuery=Y&TYPEK=sii&year=110&qryType=1" "step=1&firstin=1&off=1&TYPEK=sii&year=110&qryType=1"; do
  i=$((i+1))
  code=$(curl -sS -m 90 -A "Mozilla/5.0" -e "https://mopsov.twse.com.tw/mops/web/t05st09_2" -o r$i.html -w "%{http_code}" -d "$body" $u || echo ERR)
  echo "$(date -u +%FT%TZ) t05st09_2 v$i http=$code bytes=$(wc -c < r$i.html) 合庫=$(grep -c 5880 r$i.html) 安全性=$(grep -c 安全性 r$i.html) | $body" >> test/pref_probe.txt
  sleep 20
done
best=$(ls -S r*.html | head -1)
python3 - "$best" >> test/pref_probe.txt <<'PY'
import re,sys
t=open(sys.argv[1],encoding='utf-8',errors='replace').read()
s=re.sub(r'\s+',' ',re.sub('<[^>]+>','|',t)); s=re.sub(r'(\| ?)+','|',s)
i=s.find('5880'); print('HEAD', s[:1500]); print('5880', s[max(0,i-50):i+400])
PY
