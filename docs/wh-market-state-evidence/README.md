# 市場狀態補證產出

由 `python3 scripts/wh_extreme_audit.py` 產生。現行規則 2026-10-30（價格規則）；LINE 推播依 Ed 2026-10-30 指示暫停。

| 檔案 | 內容 |
| --- | --- |
| pit.md / pit.json | 逐日截斷重算 vs 完整序列。零差異或差異清單。並說明無法驗證的範圍。 |
| state-machine.md / state-machine.json | 進入／退出恰等於門檻、同時達標、維持與競合、退出切換、暖機與缺值。含輸入、前態、預期、實際。 |
| events.md / events.json | 各自訂窗的狀態天數。舊版調參宣稱占比僅留作歷史紀錄，不是現行規則的驗收依據。 |
| yearly.md / yearly.json | 檔內每一年的切換次數，含零次、無分數、不完整年。5093／695 口徑在 snapshot。 |
| notify.md / notify.json | 推播 dry-run 證據（mock push、不連網）：狀態變化、不變、同日重跑去重、失敗重試、未就緒、ledger 與 git 提交失敗。由 `python3 scripts/wh_notify_evidence.py` 產生。 |

> 現行規則的檢視重點是各段非常態的波段起點、極值與累積漲跌（頁面「歷次非常態期間」表），不是事件占比。

pit.md 的「無法驗證範圍」列出沒有對 `wh_prices`／`wh_build` 逐日前綴重跑的欄位、期間與資料源。

事件窗若要改，編輯 `config/wh_extreme_events.json` 後重跑。不要把自訂窗結果寫進 `ed_review` 列。

推播核對見 `scripts/wh_notify.py` 檔頭與 `docs/wh-market-state-rules.md`。試跑：

```
python3 scripts/wh_notify.py --dry-run
python3 scripts/wh_notify.py --preview-test
python3 scripts/wh_notify_evidence.py
```

`--preview-test` 的訊息帶「測試」，不會送出。
