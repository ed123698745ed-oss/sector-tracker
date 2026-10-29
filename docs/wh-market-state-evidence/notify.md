# 市場狀態推播：dry-run 證據

由 `python3 scripts/wh_notify_evidence.py` 產生。mock push 取代 LINE，不連網；規則 `2026-10-29`。
全部情境：**符合預期**（19／19）。
收件者一律遮蔽為 `configured`（有 secrets）或 `unset`；mock token／user id 已檢查未出現在任何輸出。時間戳為固定假時鐘，便於重跑比對。

## 情境總表

| id | 情境 | 每次排程結果 | mock push 次數 | 符合 |
| --- | --- | --- | ---: | --- |
| change-sends | 狀態變化 → 推播 | sent | 1 | 是 |
| unchanged-noop | 狀態不變 → 不推 | noop | 0 | 是 |
| same-day-rerun-dedup | 同日重跑（資料提交前又跑一次正式步驟）→ 去重不重推 | sent → dedup → dedup | 1 | 是 |
| fail-then-retry | 推播失敗 → 下次排程重試 | failed → sent → dedup | 4 | 是 |
| retry-only-no-record | retry-only 但 ledger 沒有失敗紀錄 → 不送 | skip | 0 | 是 |
| no-secrets | 未設定 LINE secrets → 不送、不寫 ledger | skipped_no_secrets | 0 | 是 |
| not-ready-quote-missing | 資料不足／未就緒：當日行情檔不存在 → 不推 | not_ready | 0 | 是 |
| not-ready-expect-date | 資料不足／未就緒：排程預期日與 stock_date 不同 → 不推 | not_ready | 0 | 是 |
| not-ready-short-history | 資料不足／未就緒：只有一個交易日 → 不推 | not_ready | 0 | 是 |
| not-ready-length | 資料不足／未就緒：state 與 dates 長度不一 → 不推 | not_ready | 0 | 是 |
| not-ready-score-missing | 資料不足／未就緒：非常態但該側分數缺值 → 不推 | not_ready | 0 | 是 |
| not-ready-threshold | 資料不足／未就緒：檔內門檻與程式不一致 → 不推 | not_ready | 0 | 是 |
| ledger-old-flow-sent-commit-fail | 舊流程：送達但當日資料提交失敗 → 乾淨 checkout 丟 ledger，下次重送 | sent → sent | 2 | 是 |
| ledger-new-flow-sent-data-fail | 新流程：送達、ledger 先單獨提交成功、資料提交失敗 → 下次去重 | sent → dedup | 1 | 是 |
| ledger-new-flow-failed-data-fail | 新流程：推播失敗＋資料提交失敗（ledger 已單獨提交）→ 下次重試 | failed → sent → dedup | 4 | 是 |
| ledger-both-commits-fail-failed | 已知風險（可自癒）：推播失敗＋兩段提交都失敗 → ledger 丟失，下次重跑正式步驟仍會再送 | failed → sent | 4 | 是 |
| ledger-both-commits-fail-sent | 已知風險（會重複）：送達＋兩段提交都失敗 → 下次重送一次 | sent → sent | 2 | 是 |
| ledger-retry-commit-fail | 已知風險（會重複）：retry-only 補送成功但提交失敗 → 下次 retry-only 再送 | failed → sent → sent | 5 | 是 |
| actual-repo-dry-run | 實際資料 dry-run（repo 現有 docs/wh.json，stock_date=20261029） | noop | 0 | 是 |

## 逐次執行紀錄

### change-sends

狀態變化 → 推播（流程：new）

- 第 1 次（第一次排程）：mode=`send` action=`sent` push=1 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `pushed`
  - 提交更新（含 data/ 與 ledger）：git `pushed`
  - 遠端 ledger：0→-1 sent；遠端行情檔：有

### unchanged-noop

狀態不變 → 不推

- 第 1 次：mode=`send` action=`noop` push=0 reason=`state_unchanged`

### same-day-rerun-dedup

同日重跑（資料提交前又跑一次正式步驟）→ 去重不重推（流程：new）

- 第 1 次（第一次：送達，ledger 提交成功，資料提交失敗）：mode=`send` action=`sent` push=1 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `pushed`
  - 提交更新（含 data/ 與 ledger）：git `push_failed`
  - 遠端 ledger：0→1 sent；遠端行情檔：無
- 第 2 次（第二次：行情檔未在遠端，重跑正式步驟）：mode=`send` action=`dedup` push=0
  - 提交推播紀錄（單獨、先於資料）：git `nothing_to_commit`
  - 提交更新（含 data/ 與 ledger）：git `pushed`
  - 遠端 ledger：0→1 sent；遠端行情檔：有
- 第 3 次（第三次：行情檔已在遠端，只跑 retry-only）：mode=`retry-only` action=`dedup` push=0
  - 提交推播重試紀錄：git `nothing_to_commit`
  - 遠端 ledger：0→1 sent；遠端行情檔：有

### fail-then-retry

推播失敗 → 下次排程重試（流程：new）

- 第 1 次（第一次：3 次都失敗，寫 failed）：mode=`send` action=`failed` push=3 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `pushed`
  - 提交更新（含 data/ 與 ledger）：git `pushed`
  - 遠端 ledger：0→2 failed；遠端行情檔：有
- 第 2 次（第二次：retry-only 補送成功）：mode=`retry-only` action=`sent` push=1 recipient=`configured`
  - 提交推播重試紀錄：git `pushed`
  - 遠端 ledger：0→2 failed、0→2 sent；遠端行情檔：有
- 第 3 次（第三次：retry-only 已送達，去重）：mode=`retry-only` action=`dedup` push=0
  - 提交推播重試紀錄：git `nothing_to_commit`
  - 遠端 ledger：0→2 failed、0→2 sent；遠端行情檔：有

### retry-only-no-record

retry-only 但 ledger 沒有失敗紀錄 → 不送

- 第 1 次：mode=`retry-only` action=`skip` push=0 reason=`retry_only_without_failed_record`

### no-secrets

未設定 LINE secrets → 不送、不寫 ledger

- 第 1 次：mode=`send` action=`skipped_no_secrets` push=0 recipient=`unset`

### not-ready-quote-missing

資料不足／未就緒：當日行情檔不存在 → 不推

- 第 1 次：mode=`send` action=`not_ready` push=0 reasons=['quote_file_missing']

### not-ready-expect-date

資料不足／未就緒：排程預期日與 stock_date 不同 → 不推

- 第 1 次：mode=`send` action=`not_ready` push=0 reasons=['expect_date_mismatch']

### not-ready-short-history

資料不足／未就緒：只有一個交易日 → 不推

- 第 1 次：mode=`send` action=`not_ready` push=0 reasons=['short_history']

### not-ready-length

資料不足／未就緒：state 與 dates 長度不一 → 不推

- 第 1 次：mode=`send` action=`not_ready` push=0 reasons=['length_mismatch']

### not-ready-score-missing

資料不足／未就緒：非常態但該側分數缺值 → 不推

- 第 1 次：mode=`send` action=`not_ready` push=0 reasons=['abnormal_score_missing']

### not-ready-threshold

資料不足／未就緒：檔內門檻與程式不一致 → 不推

- 第 1 次：mode=`send` action=`not_ready` push=0 reasons=['threshold_mismatch']

### ledger-old-flow-sent-commit-fail

舊流程：送達但當日資料提交失敗 → 乾淨 checkout 丟 ledger，下次重送（流程：old）

> 修正前的行為：重複推播一次。

- 第 1 次（第一次：送達，資料提交（含 ledger）失敗）：mode=`send` action=`sent` push=1 recipient=`configured`
  - 提交更新（含 data/ 與 ledger）：git `push_failed`
  - 遠端 ledger：無；遠端行情檔：無
- 第 2 次（第二次：乾淨 checkout 沒有 ledger 與行情檔，重跑正式步驟）：mode=`send` action=`sent` push=1 recipient=`configured`
  - 提交更新（含 data/ 與 ledger）：git `pushed`
  - 遠端 ledger：0→-1 sent；遠端行情檔：有

### ledger-new-flow-sent-data-fail

新流程：送達、ledger 先單獨提交成功、資料提交失敗 → 下次去重（流程：new）

- 第 1 次（第一次：送達，ledger 單獨提交成功，資料提交失敗）：mode=`send` action=`sent` push=1 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `pushed`
  - 提交更新（含 data/ 與 ledger）：git `push_failed`
  - 遠端 ledger：0→-1 sent；遠端行情檔：無
- 第 2 次（第二次：ledger 已在遠端，重跑正式步驟 → dedup）：mode=`send` action=`dedup` push=0
  - 提交推播紀錄（單獨、先於資料）：git `nothing_to_commit`
  - 提交更新（含 data/ 與 ledger）：git `pushed`
  - 遠端 ledger：0→-1 sent；遠端行情檔：有

### ledger-new-flow-failed-data-fail

新流程：推播失敗＋資料提交失敗（ledger 已單獨提交）→ 下次重試（流程：new）

- 第 1 次（第一次：推播失敗，ledger(failed) 單獨提交成功，資料提交失敗）：mode=`send` action=`failed` push=3 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `pushed`
  - 提交更新（含 data/ 與 ledger）：git `push_failed`
  - 遠端 ledger：0→1 failed；遠端行情檔：無
- 第 2 次（第二次：行情檔未在遠端，重跑正式步驟；ledger 有 failed → 補送）：mode=`send` action=`sent` push=1 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `pushed`
  - 提交更新（含 data/ 與 ledger）：git `pushed`
  - 遠端 ledger：0→1 failed、0→1 sent；遠端行情檔：有
- 第 3 次（第三次：行情檔已在遠端，retry-only → dedup）：mode=`retry-only` action=`dedup` push=0
  - 提交推播重試紀錄：git `nothing_to_commit`
  - 遠端 ledger：0→1 failed、0→1 sent；遠端行情檔：有

### ledger-both-commits-fail-failed

已知風險（可自癒）：推播失敗＋兩段提交都失敗 → ledger 丟失，下次重跑正式步驟仍會再送（流程：new）

> ledger 丟失，但因行情檔也沒提交，下次排程走正式步驟而不是 retry-only，所以仍會補送。若這是當日最後一次排程（18:20），當日就沒有下一次，需人工補救。

- 第 1 次（第一次：推播失敗，ledger 與資料提交都失敗）：mode=`send` action=`failed` push=3 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `push_failed`
  - 提交更新（含 data/ 與 ledger）：git `push_failed`
  - 遠端 ledger：無；遠端行情檔：無
- 第 2 次（第二次：乾淨 checkout 無 ledger、無行情檔 → 正式步驟重送）：mode=`send` action=`sent` push=1 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `pushed`
  - 提交更新（含 data/ 與 ledger）：git `pushed`
  - 遠端 ledger：0→2 sent；遠端行情檔：有

### ledger-both-commits-fail-sent

已知風險（會重複）：送達＋兩段提交都失敗 → 下次重送一次（流程：new）

> 無法在 repo 內完全修好：送達事實只寫在 runner 的工作目錄。workflow 會上傳 ledger artifact 供人工補提交。

- 第 1 次（第一次：送達，ledger 與資料提交都失敗）：mode=`send` action=`sent` push=1 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `push_failed`
  - 提交更新（含 data/ 與 ledger）：git `push_failed`
  - 遠端 ledger：無；遠端行情檔：無
- 第 2 次（第二次：乾淨 checkout 無 ledger → 再送一次（重複））：mode=`send` action=`sent` push=1 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `pushed`
  - 提交更新（含 data/ 與 ledger）：git `pushed`
  - 遠端 ledger：0→-1 sent；遠端行情檔：有

### ledger-retry-commit-fail

已知風險（會重複）：retry-only 補送成功但提交失敗 → 下次 retry-only 再送（流程：new）

- 第 1 次（第一次：推播失敗，提交成功）：mode=`send` action=`failed` push=3 recipient=`configured`
  - 提交推播紀錄（單獨、先於資料）：git `pushed`
  - 提交更新（含 data/ 與 ledger）：git `pushed`
  - 遠端 ledger：0→1 failed；遠端行情檔：有
- 第 2 次（第二次：retry-only 補送成功，提交失敗）：mode=`retry-only` action=`sent` push=1 recipient=`configured`
  - 提交推播重試紀錄：git `push_failed`
  - 遠端 ledger：0→1 failed；遠端行情檔：有
- 第 3 次（第三次：遠端 ledger 仍是 failed → 再送）：mode=`retry-only` action=`sent` push=1 recipient=`configured`
  - 提交推播重試紀錄：git `pushed`
  - 遠端 ledger：0→1 failed、0→1 sent；遠端行情檔：有

### actual-repo-dry-run

實際資料 dry-run（repo 現有 docs/wh.json，stock_date=20261029）

- 第 1 次：mode=`dry-run` action=`noop` push=0 reason=`state_unchanged`

## ledger 與 git 提交失敗：結論

- 修正前（`ledger-old-flow-sent-commit-fail`）：ledger 只跟著「提交更新」整包提交。該次 push 失敗時，乾淨 checkout 沒有 ledger，行情檔也不在，下次排程重跑正式步驟：若上次其實已送達就重複推一次；若上次失敗則會補送。
- 修正後：`daily.yml` 在推播步驟後**先單獨提交並 push ledger（5 次重試）**，再提交整包資料。資料提交失敗時，下次排程看得到 ledger，已送達的去重、失敗的補送（`ledger-new-flow-*`）。單獨 push 也失敗時會把 ledger 上傳成 workflow artifact `wh-notify-ledger-<run_id>`。
- 仍有的已知風險：兩段提交都失敗，或 retry-only 補送成功後提交失敗，下次可能**重複推一次**；若那是當日最後一次排程，失敗的事件當日不會再自動補送。人工補救步驟見 `docs/wh-market-state-rules.md` 第 6 節。
