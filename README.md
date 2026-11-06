# 台股族群追蹤（sector-tracker）

Ai Bot Team／Emit 維護的市場觀察網站。每個交易日盤後抓取證交所、櫃買中心收盤行情，依題材分類表與上榜規則，列出當日熱門題材、熱門數量、連續上榜天數與近期上榜次數。

**只供觀察市場，不是交易訊號。**

- 網頁：GitHub Pages（`docs/`）
- 題材分類表：`config/themes.csv`（主檔為 Drive「05_Emit工作紀錄／族群性觀察網站」的題材分類表，修改由 Ed 決定後同步至此）
- 上榜規則：`scripts/build.py` 檔頭（規則 V03）
- 每日排程：`.github/workflows/daily.yml`，台北時間週一至週五 13:52 起分段重試，16:20、18:20 仍會再抓
- 失敗通知：各排程工作失敗（含 push 重試後仍失敗）推 LINE，`scripts/notify_failure.py`
- 資料：`data/quotes/YYYYMMDD.json`，每檔個股當日漲跌% 與成交金額（億）
- 權值高價股「市場狀態」（試行、只供觀察）：規則全文 `docs/wh-market-state-rules.md`；計算 `scripts/wh_extreme.py`；推播 `scripts/wh_notify.py`（狀態改變才推；Ed 2026-10-30 指示暫停，daily.yml 該步驟為 `if: false`）；補證 `python3 scripts/wh_extreme_audit.py`
- 臺指 VIX（權值與高價股頁，只供觀察）：`scripts/vix.py`（期交所每月下載檔 log2data＋行情資訊網 getQuoteListVIX）；收盤 `data/vix_daily.json`、網頁 `docs/vix.json`、原始檔 `archive/raw/taifex_vix`；每日由 daily.yml 更新，盤中由 wh_intraday 每 5 分鐘帶入；手動補跑改 `test/VIX_TRIGGER`；期交所只公開近約 4 個月；2026/08 以前取自財經M平方圖表 46328（2016/11 起，`scripts/vix_import_mm.py`，原始檔 `archive/raw/macromicro_vix`）；測試 `python3 tests/test_vix.py`
- 可轉債追蹤（試行 CB01、只供觀察）：`docs/cb.html`；抓取 `scripts/cb_fetch.py`（櫃買 RSta0113，原始檔 `archive/raw/tpex_cb`）；計算 `scripts/cb_build.py`；排程 `.github/workflows/cb.yml`（台北 15:42 起，不推 LINE）；測試 `python3 tests/test_cb.py`

規則或題材表的修改須經 Ed 確認，並依 Emit 工作手冊第 9 節留下工作紀錄。歷史資料以現行成分股回推，有事後歸類偏差。
