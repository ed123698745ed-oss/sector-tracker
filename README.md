# 台股族群追蹤（sector-tracker）

Ai Bot Team／Emit 維護的市場觀察網站。每個交易日盤後抓取證交所、櫃買中心收盤行情，依題材分類表與上榜規則，列出當日熱門題材、熱門數量、連續上榜天數與近期上榜次數。

**只供觀察市場，不是交易訊號。**

- 網頁：GitHub Pages（`docs/`）
- 題材分類表：`config/themes.csv`（主檔為 Drive「05_Emit工作紀錄／族群性觀察網站」的題材分類表，修改由 Ed 決定後同步至此）
- 上榜規則：`scripts/build.py` 檔頭（規則 V01）
- 每日排程：`.github/workflows/daily.yml`，台北時間週一至週五 13:52 起分段重試，16:20、18:20 仍會再抓
- 資料：`data/quotes/YYYYMMDD.json`，每檔個股當日漲跌% 與成交金額（億）
- 權值高價股「市場狀態」（試行、只供觀察）：規則全文 `docs/wh-market-state-rules.md`；計算 `scripts/wh_extreme.py`；推播 `scripts/wh_notify.py`（狀態改變才推，正式推播未停用）；補證 `python3 scripts/wh_extreme_audit.py`

規則或題材表的修改須經 Ed 確認，並依 Emit 工作手冊第 9 節留下工作紀錄。歷史資料以現行成分股回推，有事後歸類偏差。
