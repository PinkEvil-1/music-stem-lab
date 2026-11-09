# 詳細任務流程與恢復

狀態：待實作的規格。下述狀態是產品執行狀態，與開發任務狀態不同。

## 狀態

| state | 意義 | 可轉移 |
| --- | --- | --- |
| queued | 已持久化、等待順序 | running、cancelled |
| running | worker 已領取 | publishing、failed、cancelled、recovering |
| publishing | 產物已驗證，準備提交 | completed、failed、recovering |
| recovering | 重啟或租約失效後對帳 | completed、queued、failed、cancelled |
| completed | manifest 與所有必要檔案均可用 | 刪除 |
| failed | 本 attempt 失敗，後續佇列可繼續 | queued（明確重試）、刪除 |
| cancelled | 已停止所有工作與子程序 | queued（明確重試）、刪除 |

running.stage 依序為 fetching、decoding、separating、mixing、verifying。
取消意圖獨立記錄；publishing 的取消與完成以資料庫提交作線性化點，先提交成功就回 completed，否則走取消及清理，不容許雙重結果。

## 使用者提交流程

1. 解析多行輸入，保留行號，驗證網址與模式。
2. 檢查模式實際可用、配額及 idempotency_key。
3. 交易建立批次、有效工作、queue_sequence 與事件。
4. 回傳逐筆結果；網頁開始輪詢，關閉頁面不影響執行。
5. 重送同 key 不重複建立工作；同 URL 新 key 可建立新工作。

## 單筆執行流程

1. 確認全域 worker 所有權，交易領取最前 queued，建立 attempt 與 fencing token。
2. 確認剩餘空間；建立此 attempt 專屬工作目錄。
3. SourceAdapter 取得單一音訊，套用時長、大小、逾時限制。
4. 以 ffprobe 確認有可解碼音軌，再解碼為模型輸入規格；限制解碼輸出大小。
5. 載入鎖定 ModelProfile，持續記錄心跳、取消及資源使用。
6. 完成分離，依模式產生目標軌與伴奏；共同時基及增益策略不可省略。
7. 驗證必要產物可解碼、規格一致、長度合理、沒有 NaN／Inf／空檔；記錄削波、峰值與雜湊。
8. 寫暫存 manifest，關閉檔案後保存 publishing 意圖，包含預期產物清單及 token。
9. 在同一檔案系統原子更名至 published；不要逐檔直接曝露。
10. 交易提交 artifact 索引、completed 與事件，條件檢查 token 及取消狀態。
11. 成功後清理不需要的暫存，再領取下一筆。

格式驗證通過不等於聽感品質通過；模型配置上線前另依 05 文件驗收。
單筆 runtime 不以「未知道正確答案」為由假裝計算分離品質分數。

## 錯誤與重試

| 錯誤 | 處理 |
| --- | --- |
| 來源刪除／私人／登入限制／直播 | failed，清楚原因，不自動無限重試 |
| 暫時網路錯誤 | 草案：最多 2 次階段內重試，退避 5 秒、20 秒；保持本筆執行權 |
| 解碼失敗／非音訊 | failed，清理不完整來源，處理下一筆 |
| GPU OOM | 先終止本次推論並釋放資源；只允許一次已驗證的小 segment 配置重試，記錄新參數 |
| 無 GPU 或 OOM 降級仍失敗 | failed；CPU 降級須事先選定，不偷偷改變執行時間預期 |
| 推論／外部程序逾時 | 終止整個程序樹、確認退出，failed |
| 磁碟不足 | 停止寫入、failed；暫停領取新工作並提示釋放空間 |
| 已知輸入錯誤 | 不重試 |
| 未分類例外 | failed，保留遮罩後診斷與 attempt，後續工作可繼續 |

數值是待驗證預設；不允許重試次數乘上整個 pipeline 後變成無界重跑。
手動重試排到尾端，保留舊 attempt，不能覆蓋先前已發表的證據。

## 取消流程

queued 直接取消。running 設 cancel_requested，worker 停止啟動新階段，通知子程序退出；超過寬限時間強制終止程序樹。
確認程序已退出、停止心跳及禁止發布後，才寫 cancelled。
不刪除仍由程序持有的檔案；已完成產物不因重複取消而移除。
介面區分「取消中」與「已取消」。

## 重啟與恢復流程

1. 取得全域 worker 所有權；若舊程序仍活躍，不啟動新推論。
2. 掃描非終止工作，標 recovering，檢查取消意圖、租約與 attempt 記錄。
3. publishing 且 published manifest 完整一致：對帳 token 與預期清單後補提交 completed。
4. 意圖存在但檔案不完整：不對外提供，隔離舊 attempt，重新入列或 failed，保留事件。
5. running 且無可提交結果：終止／確認舊程序退出後，從新 attempt 重跑，最多一次自動恢復。
6. 對帳資料庫未索引的孤立檔案；僅清理本專案已確認不活躍的暫存。
7. 重啟恢復工作保留原順序，明確手動重試才排尾端。
8. 檢查已完成工作是否有檔案遺失；標記 artifact unavailable，不能繼續宣稱可下載。

第一版從頭重做中斷工作，不宣稱支援模型推論中途續算。

## 刪除與備份

只刪除由 job_id 推導且解析後位於 data/jobs 下的路徑，拒絕符號連結／路徑穿越。
以 deleting 意圖或 tombstone 協調檔案與索引刪除，程序中斷後可續清理。
備份資料庫需使用一致性備份流程，搭配已發布檔案及 manifest；不僅複製執行中的 SQLite 主檔。
實作前補上備份還原測試及磁碟維護操作文件。
