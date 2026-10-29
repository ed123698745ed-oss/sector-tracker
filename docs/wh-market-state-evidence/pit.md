# 時點／前視：逐日截斷重算

- 結論：**零差異**
- 受檢日 5591／序列 5591；與發布 wh.json 的完整重算：零差異
- 資料日 `20261029`，規則 `2026-10-29`

對每個受檢交易日 i，只保留 dates、taiex、全市場 n/ld/lu/dd、turnover、conc 的前綴 [:i+1]（含 i），呼叫 wh_extreme.compute，比對一次完整序列在 i 的 state 與三位小數分數。

## 無法驗證

- 沒有各歷史日收盤當下的行情、指數、母體快照。現在的 data/quotes 與 archive/raw 可能含事後修正、補檔與除權息／減資／分割參考價補算。截斷重算證明的是「這份現存輸入」下，分數與狀態只用到該日（含）為止，不能證明當時公布的版本與現在檔案相同。
- 普通股母體是現存每日行情檔裡符合 is_common 的代號，不是當日凍結的指數成分或當時的上市櫃名單影像。
- 2009 年以前加權指數取自月檔 FMTQIK 的當日收盤列。公式沒有讀該日之後的列，但檔案本身可能是後來才下載或覆蓋的。
- 跌停家數、離高點分布等 groups.all 欄位沿用已建置的 wh.json，本次沒有把 wh_prices／wh_build 對每個前綴再跑一次。程式裡滾動窗是往回看（含當日或前 N 日，不含未來日）；這段上游沒有做逐日截斷重跑。
- 同一交易日盤中、收盤檔公布前的數值沒有另存。狀態只在該日 quotes 檔存在後由整日資料計算。
- Ed 交審事件的原始起迄與當時資料版本不在 repo，見 events.md。

## 無法驗證範圍

上面的截斷重算只對 `wh_extreme.compute` 這一層做。**沒有**對 `wh_prices.py`／`wh_build.py` 逐日前綴重跑（`wh_prices` 一次讀入全部 `data/quotes` 寫成單一 `cache/wh_px.json.gz`，`wh_build` 再以全期還原價與現行名單、事件表建置），所以下列欄位、期間、資料源的時點性質未經驗證：

| 欄位 | 期間 | 資料源 | 為何無法驗證 |
| --- | --- | --- | --- |
| groups.all.ld／lu（5 日跌停、漲停家數占比的分子） | 全期（20040211～資料日） | cache/wh_px.json.gz 的 lim（wh_prices.py 由 data/quotes、archive/raw/twse_events、twse_newlisting、tpex 判定） | 沒有逐日前綴重跑 wh_prices。除權息／恢復買賣日的漲跌停價取自 twse_events，該目錄由 whext.yml 事後批次抓取，不是各日當下取得；判定規則也經多次複核修訂（git log）。 |
| groups.all.n（當日有效家數，占比分母） | 全期 | wh_build.py 以 cache/wh_px.json.gz 計數 | 同上，未逐日前綴重跑；母體是現存行情檔裡符合 is_common 的代號，不是當日凍結名單。 |
| groups.all.dd（離近 250 日高點 ≥20% 占比） | 全期；個股上市未滿 250 日不計 | wh_build.py 的還原價（以每日漲跌% 連乘）與盤中最高價 | 還原價以全期一次建置，未逐日前綴重跑。滾動窗依程式是往回看，但沒有實際截斷驗證；現存漲跌% 可能含事後補算的參考價。 |
| taiex（加權指數點位） | 20040211～20081231 | archive/raw/twse_fmtqik 月檔（現存 200402～201412） | 月檔由 whext.yml 事後下載；公式只讀當日列，但無法證明月檔內容與當日公布值相同。 |
| taiex（加權指數點位） | 20090101～資料日 | archive/raw/twse/YYYYMMDD.json.gz（MI_INDEX）；缺檔或缺列時退回 FMTQIK | 沒有標記哪些日子實際用了退回值；原始檔抓取時間未逐日記錄。 |
| turnover、conc（成交值、前五大集中度） | 全期 | data/quotes/YYYYMMDD.json | 截斷重算有用到這兩條，證明 compute 不讀未來；但行情檔本身可能是 backfill 補抓或修正後版本，repo 未保存各日公布當下版本。 |
| 母體口徑（上市 vs 上市櫃） | 20070702 以前 | archive/raw/tpex 現存檔 | 頁面註記櫃買資料 2007/07 起，此前全市場欄位僅上市普通股。這是口徑變化，不是前視；未另做上市-only 的對照重算。 |
| 盤中值 | 全期 | 無 | 收盤檔公布前的數值沒有另存，無從比較盤中與收盤後判定。 |
| Ed 原交審事件表（起迄、母體、資料版本） | 交審表所列各窗 | 不在 repo | 原交審事件表尚未驗證；config/wh_extreme_events.json 的 ed_review 起迄為空，見 events.md。 |
