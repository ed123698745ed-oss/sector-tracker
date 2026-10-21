import json, os, urllib.request
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0 Safari/537.36"}
os.makedirs("/tmp/p", exist_ok=True)
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r:
            return r.status, r.read()
    except Exception as e:
        return getattr(e, "code", None), str(e).encode()
st, b = get("https://www.tpex.org.tw/openapi/swagger.json")
hits = [f"swagger {st} {len(b)}"]
try:
    s = json.loads(b)
    for p, v in s.get("paths", {}).items():
        t = json.dumps(v, ensure_ascii=False)
        if any(k in t for k in ("除權", "除息", "exright", "參考價")):
            hits.append(p + " " + str([o.get("summary") for o in v.values() if isinstance(o, dict)]))
except Exception as e:
    hits.append("ERR " + str(e))
open("/tmp/p/swagger_hits.txt", "w").write("\n".join(hits))
urls = [
 "https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?l=zh-tw&d=115/06/01&ed=115/07/31",
 "https://www.tpex.org.tw/www/zh-tw/exright/dailyQuo?startDate=2026/06/01&endDate=2026/07/31&response=json",
 "https://www.tpex.org.tw/www/zh-tw/exright/exDailyQ?startDate=2026/06/01&endDate=2026/07/31&response=json",
 "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate=2026/06/01&endDate=2026/07/31&response=json",
 "https://www.tpex.org.tw/openapi/v1/tpex_exright_daily",
]
for i, u in enumerate(urls, 1):
    st, b = get(u)
    open(f"/tmp/p/c{i}.txt", "w").write(f"{u}\nHTTP {st}\n" + b[:3000].decode("utf-8", "replace"))
