#!/bin/bash
curl -sS -m 90 -A "Mozilla/5.0" -e "https://mopsov.twse.com.tw/mops/web/t108sb19" -o r1.html -d "step=1&firstin=1&off=1&queryName=co_id&inpuType=co_id&TYPEK=all&isnew=false&co_id=1519&year=114" https://mopsov.twse.com.tw/mops/web/ajax_t108sb19
echo "== t108sb19 1519 114 list $(date -u +%FT%TZ) bytes=$(wc -c < r1.html)" >> test/pref_probe.txt
grep -o "<form[^>]*>\|<input[^>]*>\|onclick=\"[^\"]*\"\|onclick='[^']*'" r1.html | head -40 >> test/pref_probe.txt
python3 - r1.html >> test/pref_probe.txt <<'PY'
import re,sys
t=open(sys.argv[1],encoding='utf-8',errors='replace').read()
s=re.sub(r'\s+',' ',re.sub('<[^>]+>','|',t)); s=re.sub(r'(\| ?)+','|',s)
i=s.find('公告日期'); print('LIST', s[i:i+800])
PY
