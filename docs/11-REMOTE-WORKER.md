# 分開網站與模型執行器

日期：2026-11-09。需求：R001–R008、R011–R013。新增任務 T019。
使用者決定模型在另一台電腦執行，因此本機 GPU／模型測試延後，不再阻擋網站實作。

## 本輪實作與後續邊界

本機使用 Python FastAPI、SQLite、本地磁碟與原生 HTML／CSS／JavaScript。
本機內建兩種 worker：明確 opt-in 的合成示範，以及啟動參數允許後的原始音訊下載。
遠端 API 已實作，但尚未開發可執行 Demucs 的遠端程式，也沒有跨機連線或模型品質通過證據。

示範工作使用 execution_kind=demo，真實工作使用 real；遠端 worker 只能領取 real。
示範只產生合成測試音，不發送 YouTube 請求。completed 與「音質驗收通過」是不同概念。
真實分離工作提交後，會等待支援該 mode 的執行器，不會自動用示範或 CPU 取代。

目前遠端 claim 回傳正規化來源網址，由未來遠端 pipeline 取得來源並處理。
本機 download_audio 是獨立工作；尚未將它自動串成同一筆分離工作的來源前處理。
後續可加入「由 coordinator 提供已取得來源」的傳輸方式，需同步修訂契約與整合測試。

## 遠端接入與權限

服務預設只監聽 127.0.0.1。跨機時先使用受控的私人通道，例如將遠端主機的 loopback 轉送到 coordinator 的 loopback。
不需要改成公開監聽即可進行私人 tunnel 整合；此通道尚未實測。
worker API 使用 Authorization: Bearer <REDACTED>。實際值由環境變數 MUSIC_STEM_WORKER_TOKEN 提供，不寫進原始碼或文件。
每次領取另回傳 attempt_token，後續請求用 X-Attempt-Token 攜帶；此值只在 claim 回傳，不出現在公開工作列表或 manifest。

一般工作管理 API 沒有遠端多使用者登入功能。不要把整個服務或 worker token 對外公開；公網／多使用者授權不在本輪交付範圍。
瀏覽器同來源限制、允許 Host、檔案路徑檢查及 token 驗證已有測試。

## Worker API

| 方法與路徑 | 請求／用途 |
| --- | --- |
| POST /api/worker/claim | worker_id、modes；回傳 job 或 null，以及 lease_seconds |
| POST /api/worker/jobs/{id}/heartbeat | stage、progress；需 X-Attempt-Token；回傳 cancel_requested |
| PUT /api/worker/jobs/{id}/uploads/{kind}?extension=.wav | application/octet-stream 原始音訊 bytes；需 X-Attempt-Token |
| POST /api/worker/jobs/{id}/complete | profile_id、version、description、選填 weights_sha256；驗證全部產物後發布 |
| POST /api/worker/jobs/{id}/finish | state=failed／cancelled、選填 error_code；執行器確認已停止後釋放工作 |

API schema 可由 /openapi.json 取得。created_at、updated_at、lease_until、events.time 及 manifest.completed_at 目前以 UTC Unix 秒數提供，前端換算為本機時間；原始規格的 ISO 8601 為尚未採用的表示方式。未設定主 token 回 503，錯誤 token 回 401，過期或被撤銷的執行嘗試回 409。
complete 目前信任受控 worker 提供的 profile，尚未實作權重白名單或模型品質登錄；capabilities 明確回傳 model_inference_available=false。

## 領取與執行

1. 以支援的 modes 呼叫 claim，沒有可領工作時退避輪詢。
2. 保存 job.id、attempt_id、attempt_token、execution_kind 與 source_url。
3. 依 fetching、decoding、separating、mixing、verifying 回報階段；未知進度用 null。
4. 預設租約 60 秒，建議每 10 秒送心跳；上傳大型檔案時也需另一執行緒持續送心跳。
5. cancel_requested=true 時，先停止計算及子程序，再呼叫 finish cancelled。
6. 完成後上傳必要音檔；確認成功後才呼叫 complete。
7. 任何 STALE_ATTEMPT／LEASE_EXPIRED 回應都應停止本次執行，不能改成重複提交工作。
8. 任務失敗以分類 error_code 回報，不把原始命令、憑證或完整路徑當錯誤訊息傳回。

有界重試由未來遠端執行器負責實作，不能無限重跑模型。程式目前僅為本機下載器設定有限 socket 重試與總逾時。

## 必要產物與發布

| mode | 音檔種類 |
| --- | --- |
| download_audio | source |
| remove_vocals | source、vocals、no_vocals |
| remove_guitar | source、guitar、no_guitar |

manifest 由 coordinator 生成，不能由 worker 任意指定檔案路徑。
分離輸出需為 PCM WAV；同組 WAV 的取樣率、聲道及 frames 必須一致。
WAV 支援 1–2 聲道、16／24／32-bit 整數 PCM、8–192 kHz，時長上限 20 分鐘。
來源可使用 WAV、WebM、M4A、MP3、Ogg／Opus、FLAC。非 WAV 在容器檢查後，還需 FFmpeg 實際解碼，超時長、壞音訊或解碼逾時均不發布。驗證最多解碼上限加一秒、單聲道 16 kHz PCM，輸出記憶體受時長限制；原始檔案保留原格式。

上傳檔案保存於本次 attempt 的 work，尚未 complete 的檔案不提供公開下載。
發布意圖先寫入 SQLite，再把 work 原子更名為 published，最後提交 artifact 索引與 completed。
若更名後、資料庫提交前中斷，重新啟動會核對 manifest 與雜湊，補完提交。
已有取消意圖時不發布，等待執行器停止確認或人工恢復。
下載時重新核對大小與 SHA-256，缺檔或損毀回 410；Range 由 FileResponse 處理。

## FIFO、失聯與恢復

只有整個佇列最前方可領取；worker 不支援前方工作時不能跳過。
無論本機／遠端，同時至多一筆 running／publishing／recovering。
執行器失聯不代表舊程序已停止。租約逾時轉 recovering，保留全域執行位置。

使用者必須先確認舊執行器已停止，再從 UI 恢復，或：
POST /api/jobs/{id}/recover，傳 old_worker_stopped=true。
系統撤銷舊 token，再依原順序重新入列；若有取消意圖則轉 cancelled。
手動 retry 才排到尾端。UI 明確區分取消中與已取消。
這個確認是產品的恢復操作，不是 Agent 要求使用者重新授權開發。

## 尚待完成的整合

- 遠端模型程式、環境盤點、權重與授權檢查。
- 真實跨機連線、心跳、網路中斷、大檔傳輸與取消。
- 更多來源失敗與取消情境；使用者提供的單一真實 YouTube 來源已通過端到端驗證，見 evidence/SOURCE-001.md。
- 模型版本／參數完整記錄、音質驗收與長曲資源量測。
- 正式部署存取與備份演練；本輪僅完成本機可重現驗證。
