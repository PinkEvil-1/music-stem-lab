# EXPORTS-001：額外版本勾選與 WAV 播放驗證

日期：2026-11-09。需求 R003、R004、R009、R014；驗收 A017；任務 T028、T029。
後端提交：21a0b9d。模型推論與真實伴奏混音仍未執行。

## 後端

tests/test_extra_exports.py：17 passed，1 個既有第三方棄用警告，46.67 秒。
四種 extra_exports 組合（無、去人聲、去吉他、兩者）皆能保存並依契約發布。
原生 stems 全部保留，未選伴奏拒絕上傳；缺必要產物則拒絕發布。
額外選項參與 idempotency；更換選項不可重用同 key，排列不同但相同組合可去重。
模型缺少所選目標類別時不領取；沒有勾選時不要求相應類別。
覆蓋無效音軌名稱、重試／跨 Store 保存、attempt 能力快照與 v1 資料加欄位升級。

既有 tests/test_coordinator.py 回歸結果先為 41 passed／1 failed。
失敗檢查原本逐筆 HTTP 讀取三個工作，在不同時間點觀察兩筆 running，造成假性併行。
改為一次 SQLite SELECT COUNT 查詢同時間活躍數，重跑該案例為 1 passed（4.38 秒）。
因此59個後端案例已分批取得通過結果；未宣稱同一輪完整 pytest 顯示59 passed。
所有測試使用獨立資料與合成音，未修改預設工作室的已下載音檔。

## 瀏覽器

node scripts/browser-smoke.mjs：PASS，10 項檢查。
檢查：server_http、browser_submit_two_jobs、demo_fifo_completion、artifact_dialog、audio_range、
independent_export_checkboxes、export_options_persisted、wav_playback、mobile_no_overflow、
no_browser_errors。

- 僅下載模式的額外選項停用。
- 切成模型分軌時，兩項預設都不勾。
- 勾去人聲不會連動勾去吉他；兩項可同時選取。
- 切回僅下載會停用選項；切回分軌可保留勾選。
- 兩筆示範工作保存 extra_exports，皆完成發布。
- 每筆為1來源＋6類合成 native stems＋2個選填伴奏，共9個 WAV 播放器，加1份 manifest。
- 瀏覽器實際播放一秒合成 PCM WAV，確認 duration=1、playing=true、播放時間前進；測試設靜音避免干擾。
- Range 回206，手機390px無水平溢出，瀏覽器無錯誤。
- 人工檢視桌機與手機截圖，選項、工作摘要與說明皆可見。

截圖及原始結果（已排除 Git）：
.tmp/browser-1794217269026/desktop.png
.tmp/browser-1794217269026/mobile.png
.tmp/browser-1794217269026/result.json

## 限制

上述伴奏為合成測試音，不代表去人聲／去吉他演算法已實作。
正式模型在另一台電腦接入後，仍須驗證實際音質、混音增益與對齊。
WAV 指本專案 PCM WAV；不保證所有 WAV 內部編碼或所有舊型播放器都相容。
