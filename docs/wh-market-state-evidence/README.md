# 市場狀態補證產出

由 `python3 scripts/wh_extreme_audit.py` 產生。正式門檻沒有改，正式推播沒有關。

| 檔案 | 內容 |
| --- | --- |
| pit.md / pit.json | 逐日截斷重算 vs 完整序列。零差異或差異清單。並說明無法驗證的範圍。 |
| state-machine.md / state-machine.json | 進入／退出恰等於門檻、同時達標、維持與競合、退出切換、暖機與缺值。含輸入、前態、預期、實際。 |
| events.md / events.json | 事件表欄位定義。Ed 原交審窗未驗證／待補起訖。Eve 自訂窗另行對照，不當成原表。 |
| yearly.md / yearly.json | 檔內每一年的切換次數，含零次、無分數、不完整年。5093／695 口徑在 snapshot。 |

事件窗若要改，編輯 `config/wh_extreme_events.json` 後重跑。不要把自訂窗結果寫進 `ed_review` 列。

推播核對見 `scripts/wh_notify.py` 檔頭與 `docs/wh-market-state-rules.md`。試跑：

```
python3 scripts/wh_notify.py --dry-run
python3 scripts/wh_notify.py --preview-test
```

`--preview-test` 的訊息帶「測試」，不會送出。
