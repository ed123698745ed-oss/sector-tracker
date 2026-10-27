#!/bin/bash
curl -sS -m 90 -A "Mozilla/5.0" -e "https://mopsov.twse.com.tw/mops/web/t108sb19" -o r1.html -d "firstin=true&colorchg=&TYPEK=sii&isnew=false&id=&DATE1=20250708&SEQ_NO=1&COMP=1519&kind=&SKIND=G&step=2" https://mopsov.twse.com.tw/mops/web/ajax_t108sb22
echo "== t108sb22 1519 20250708 detail $(date -u +%FT%TZ) bytes=$(wc -c < r1.html)" >> test/pref_probe.txt
python3 - r1.html >> test/pref_probe.txt <<'PY'
import re,sys
t=open(sys.argv[1],encoding='utf-8',errors='replace').read()
s=re.sub(r'\s+',' ',re.sub('<[^>]+>','|',t)); s=re.sub(r'(\| ?)+','|',s)
i=s.find('配'); print('DETAIL', s[max(0,i-300):i+2500])
PY
