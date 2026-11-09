# 技術設計草案

狀態：提案，尚未定案或實作。以個人部署、易於維護及可重現為優先。

## 邊界與候選堆疊

瀏覽器 → 本地 API → 持久化工作資料庫 → 單一背景執行器 → 來源 adapter／解碼器／分離模型／檔案儲存。
瀏覽器不直接呼叫模型，API 接收工作後立即回傳，不維持長連線等待完整音訊處理。

候選為 Python API（例如 FastAPI）、SQLite、Python 推論 worker、簡單前端與本地磁碟。
原因是主要分離生態使用 Python，單使用者不必先導入訊息佇列或多個服務。
以上是工程建議；如改選 .NET API 或其他前端，先記錄決策及維護成本，保留相同工作契約。
目前未建立任何 .NET、Python 或前端程式，也未評估指定版本文件。

| 元件 | 責任 |
| --- | --- |
| Web | 輸入網址、選模式、顯示工作列表、試聽與下載 |
| API | 驗證、建立工作、取消／重試／刪除、授權及下載控制 |
| JobStore | 保存順序、狀態、租約、事件及產物索引 |
| Worker | 一次完成一筆流程、心跳、逾時與恢復 |
| SourceAdapter | 線上取得或合法本地測試來源；禁止任意站點 |
| AudioPipeline | 解碼、分離、重混、音訊驗證 |
| ArtifactStore | 嘗試隔離、原子發布、manifest 與清理 |
| ModelRegistry | 鎖定權重、參數、支援類別及版本 |

## 佇列語意

- FIFO 按提交交易內分配的 queue_sequence，批次依輸入順序，避免時間戳碰撞。
- 同時至多一筆「下載至發布」流程執行；第一版不預抓下一筆。
- 批次逐筆驗證：有效項目入列，無效項目回傳對應錯誤，不使整批失敗。
- 透過交易領取工作與全域 worker 鎖／租約，避免重複啟動 worker 造成並行。
- 至少一次執行語意搭配冪等發布；不宣稱跨程序 exactly-once。
- 重試保留原工作，新增 attempt，分配新的佇列序號排到尾端，不插隊。
- 建立請求帶 idempotency_key；相同 key 與 payload 回傳原結果，不重複入列；不同 payload 回 409。
- 相同網址以不同 key 提交可建立新工作。影片身分正規化不等於自動跨工作共用檔案。
- 租約到期不能直接啟動第二個活躍推論。單機先確認舊程序退出；fencing token 防止舊 worker 發布。私人伺服器多 worker 不在第一版範圍。

## 資料實體草案

| 實體 | 必要資訊 |
| --- | --- |
| Job | job_id、batch_id、來源類型／正規化 video_id、mode、queue_sequence、state、stage、created_at、updated_at、attempt_count、cancel_requested、error_code |
| Attempt | attempt_id、job_id、worker_id、fencing_token、租約／心跳、開始／結束、模型快照、參數、階段與退出原因 |
| Artifact | artifact_id、job_id、attempt_id、kind、相對路徑、大小、SHA-256、音訊規格、發布狀態 |
| Event | event_id、job_id、attempt_id、舊新狀態、時間、遮罩後原因 |
| ModelProfile | profile_id、程式版本、權重來源／雜湊、授權證據、支援模式／stems、推論與後處理參數 |

雜湊僅適用本專案音訊產物與合法模型，不授權讀取其他專案機密設定。
對外使用 UTC ISO 8601 時間，介面依使用者時區顯示。時間與大小的單位必須明確。

## API 契約草案

| 方法與路徑 | 行為 |
| --- | --- |
| POST /api/jobs/batch | 輸入 urls、mode、idempotency_key；回傳逐筆 index、job_id 或 error；有效項目建立後回 202 |
| GET /api/jobs | 分頁列出工作與 queue_position；位置是快照 |
| GET /api/jobs/{id} | 回傳狀態、階段、進度、錯誤、attempt 與 artifacts |
| POST /api/jobs/{id}/cancel | 設取消意圖，冪等；不能立即宣稱子程序已終止 |
| POST /api/jobs/{id}/retry | 僅允許 failed／cancelled，建立新 attempt 排到尾端 |
| GET /api/artifacts/{id}/content | 限已發布產物；支援音訊 Range 試聽與下載 |
| DELETE /api/jobs/{id} | 排隊或終止狀態可刪；執行中回 409，先取消再刪 |
| GET /api/capabilities | 公開實際可用模式、類別、版本及輸入限制，不曝光主機路徑 |

全批無有效項目回 422；未知工作 404；狀態衝突 409；儲存不足拒絕入列並給可辨識錯誤。
錯誤應包含 code、可讀訊息、是否可重試；不回傳原始命令、完整路徑或憑證。

## 儲存草案

data/jobs/<job_id>/attempts/<attempt_id>/work/ 存未完成產物。
data/jobs/<job_id>/attempts/<attempt_id>/published/ 存已提交產物。
manifest.json 記錄 schema_version、來源 ID、模式、權重與程式版本、增益／延遲、artifact 清單、規格、雜湊及完成時間。
manifest、音檔與資料庫跨資源無共同交易，須使用發布意圖與恢復對帳，詳見 04 文件。

保留來源編碼檔並另製規格化 PCM。內部候選為 float32、44.1 kHz、雙聲道；依選定模型調整並記錄，單聲道來源標明，不聲稱恢復成立體聲。
對外建議 WAV PCM 24-bit；source 提供實際格式，MP3 可作後續選項。
設定檔、音檔、模型及資料庫不進入 Git；規格與遮罩證據可版本控制。

儲存估算：秒數 × 取樣率 × 聲道數 × 每樣本 bytes × 檔案數。
例如 5 分鐘、44.1 kHz、雙聲道 float32 單檔約 106 MB（十進位）；還須加來源、各軌、暫存與重試空間，不能只按壓縮檔大小預估。

## 輸入與執行安全

只接受明列 YouTube host 與合法影片 ID；處理 youtu.be、watch 與 shorts，清除不必要 query，拒絕播放清單自動展開。
拒絕 userinfo、非 HTTPS、非允許主機、任意檔案路徑及內網 URL；adapter 不可被改作任意 URL fetcher。
外部程序使用參數陣列與固定執行檔，不拼接 shell；不繼承使用者 cookie／瀏覽器登入。
FFmpeg 只處理已落地檔案，禁用不需要的網路協定。標題與錯誤訊息需 HTML escape。
下載量、時長、解碼樣本數、磁碟及執行逾時設硬限制，不能只信任網站 metadata。
