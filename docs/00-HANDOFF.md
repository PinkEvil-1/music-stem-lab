# 接手狀態

更新：2026-11-09（Asia/Taipei）。
當前階段：LOCAL_COORDINATOR_IMPLEMENTED。模型與 GPU 工作依使用者指示延後。

## 使用者最新指示

模型會在另一台電腦執行，本機先跳過跑模型，執行其他部分。
此指示取代原先「模型驗證完成後才做網站」的順序，不需要再次確認是否可開發網站。
原始需求仍為個人網站、YouTube 音訊取得、去人聲／去吉他、儲存、多筆依序執行與可持續接手文件。

最新提交規則：每完成可獨立驗證的小任務，自行檢查、驗證、同步相關文件並立即 commit，不累積到整輪結束，也不再詢問是否 commit。規則見 AGENTS，依據見 D012。

## 已實作

- 原生 HTML／CSS／JavaScript 網頁，Python FastAPI、本地 SQLite。
- 批次網址驗證、正規化、請求去重、工作列表、分頁及狀態。
- 嚴格 FIFO、跨 worker 交易領取、租約、取消、重試排尾端及人工恢復。
- 受 token 驗證的遠端工作領取、心跳、檔案上傳及完成 API。
- 音檔格式／WAV 規格、雜湊與必要產物驗證，manifest、原子發布、重啟對帳。
- 試聽／Range 下載、配額、刪除 tombstone 與離線備份還原。
- 明確標示的合成音示範；不下載或分離歌曲。
- 需顯式啟用的原始音訊下載 adapter，不使用個人 cookie。
- 專案 .venv 已安裝網站與測試依賴；requirements.lock 已保存版本。

實作與驗證證據見 [LOCAL-001](evidence/LOCAL-001.md) 與 [SOURCE-001](evidence/SOURCE-001.md)；模型音質尚未驗證。預設工作室已匯入這次真實來源 completed 工作。

## 如何啟動

在專案根目錄：
.\.venv\Scripts\python.exe -m music_stem_lab
瀏覽 http://127.0.0.1:8000 。實際操作與備份命令見根 README。

預設不啟用真實來源下載；需要時加 --enable-download。
模型未接入前，real 分離工作會停在佇列，且嚴格 FIFO 會阻擋後方工作。
體驗完整流程請先取消前方尚無執行器的 real 工作，再勾選示範。

## 尚未完成／未經驗證

- 未安裝 PyTorch、CUDA、Demucs 或任何模型權重。
- 沒有實際分離歌曲、音質分數、GPU 效能或模型授權通過紀錄。
- 遠端 API 已測，但沒有真實跨機 worker 或私人通道測試。
- 使用者提供來源的真實 YouTube 下載、解碼及保存已通過，見 evidence/SOURCE-001.md；其他來源與失敗情境仍需擴充驗證。
- FFmpeg 完整解碼與時長已通過合成素材及提供來源驗證；更完整失敗與取消情境仍待擴充。本輪以 FFmpeg 解碼取代獨立 ffprobe 依賴。
- 模型參數、權重白名單與完整來源前處理串接仍待遠端實作。
- 尚未部署到公網或私人伺服器；已有依範圍拆分的本機 Git commit，尚未 push。對照見工作日誌 W009。

## 下一個接手者

1. 讀 AGENTS、README、06 任務、07 決策及 11 遠端契約。
2. T016 提供來源實測已完成；下一步擴充 T025 的來源失敗／取消整合測試，等待模型主機時繼續驗證控制面。
3. 為真實環境補上下載中取消、總時長與大小限制的整合測試。
4. 等使用者準備好另一台電腦後，盤點那台環境並開發遠端模型執行器。
5. 再進行 T011–T015／T017 的音質、權重許可與效能驗證；不要把本機環境當遠端基線。
6. 遠端接入前先保持 loopback，透過受控私人通道，不直接公開一般管理 API。
7. 每完成一個小任務，按改動範圍驗證並更新相關任務、證據與接手紀錄，立即自行 commit；不等整輪結束。

## 主要程式入口

API：music_stem_lab/app.py；工作狀態：store.py；檔案：artifacts.py。
本機執行器：local_worker.py；來源：download_task.py；備份：maintenance.py。
網頁：music_stem_lab/static/；測試：tests/；瀏覽器驗證：scripts/browser-smoke.mjs。

機密／執行資料：data/、.venv/、.tmp/、models/、.env* 已排除 Git。
環境報告 ENV-001 只是先前本機快照。產品、架構與舊技術說明若有差異，以本輪 D010 及 11 文件為準。
