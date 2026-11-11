# 接手狀態

更新：2026-11-09（Asia/Taipei）。
當前階段：LOCAL_GPU_TRIAL。單機 GPU 試用已接通（T031）。

## 使用者最新指示

使用者要求同一台電腦啟動單機試用。對應 D015、T031。
RTX 2070 SUPER（8 GiB）已通過 CUDA 驅動與 Demucs 六軌合成音推論，見 [ENV-002](evidence/ENV-002.md)。
新工作採 6 秒分段、25% 重疊、3 次時移，見 [LOCAL-MODEL-002](evidence/LOCAL-MODEL-002.md)。
網站協調器已實作，模型驗證可獨立進行。
原始需求仍為個人網站、YouTube 音訊取得、去人聲／去吉他、儲存、多筆依序執行與可持續接手文件。

最新分軌範圍：只使用所選模型／權重原生提供的軌數與類別；不要求逐把吉他獨立分軌。R010、T030、Q004 已取消，不再視為延後或未完成；去人聲與 guitar 類別整體移除仍保留。依據見 D013。

最新輸出需求 D014：基本保存模型全部原生音軌，去人聲／去吉他改為獨立額外勾選，預設不勾；雙選產生兩個伴奏。後端契約 T028 與網頁獨立 checkbox T029 均已驗證，見 evidence/EXPORTS-001.md，詳見 13-EXTRA-EXPORTS.md。

最新提交規則：每完成可獨立驗證的小任務，自行檢查、驗證、同步相關文件並立即 commit，不累積到整輪結束，也不再詢問是否 commit。規則見 AGENTS，依據見 D012。

## 已實作

- 原生 HTML／CSS／JavaScript 網頁，Python FastAPI、本地 SQLite。
- 批次網址驗證、正規化、請求去重、工作列表、分頁及狀態。
- 嚴格 FIFO、跨 worker 交易領取、租約、取消、重試排尾端及人工恢復。
- 受 token 驗證的遠端工作領取、心跳、檔案上傳及完成 API。
- 音檔格式／WAV 規格、雜湊與必要產物驗證，manifest、原子發布、重啟對帳。
- 試聽／Range 下載、配額、刪除 tombstone 與離線備份還原。
- 新的本機下載與分軌產物採「類型 - 影片名稱」（T032）。
- 明確標示的合成音示範；不下載或分離歌曲。
- 需顯式啟用的原始音訊下載 adapter，不使用個人 cookie。
- 網站與測試依賴曾於舊主機的 .venv 驗證，版本記錄在 requirements.lock。

實作與驗證證據見 [LOCAL-001](evidence/LOCAL-001.md) 與 [SOURCE-001](evidence/SOURCE-001.md)；模型音質尚未驗證。預設工作室已匯入這次真實來源 completed 工作。

## 如何啟動

Windows 雙擊專案根目錄的 `Start Music Stem Lab.cmd` 啟動（T033），關閉「Music Stem Lab」CMD 視窗會停止服務與分軌子程序（T036、T037）。本機 Python 環境與權重已搬至專案根目錄下的 .venv 與 models，離線備份在 models/wheels（T038）。手動啟動見 README。已完成的工作可從列表或詳情開啟結果資料夾。

在專案根目錄：
.\.venv\Scripts\python.exe -m music_stem_lab
瀏覽 http://127.0.0.1:8000 。實際操作與備份命令見根 README。

預設不啟用真實來源下載；需要時加 --enable-download。
依 README 帶入 --model-checkpoint 後，本機會領取 real 分軌工作。未配置模型時，這類工作會等待執行器。
體驗完整流程請先取消前方尚無執行器的 real 工作，再勾選示範。

- T039 已加入首次啟動檢查與建置，操作見 README。

- T040 已加入三組模型預設。下一個任務為 T041 硬體偵測與建議比較。

## 尚未完成／未經驗證

- 新主機上的模型環境與驗證狀態見 ENV-002；舊機的網站 .venv 需按 README 在新 checkout 重建。
- 合成音的 GPU 效能已量測。實際歌曲、正式音質與模型權重授權待驗證。
- 遠端 API 已測，但沒有真實跨機 worker 或私人通道測試。
- 使用者提供來源的真實 YouTube 下載、解碼及保存已通過，見 evidence/SOURCE-001.md；其他來源與失敗情境仍需擴充驗證。
- FFmpeg 完整解碼與時長已通過合成素材及提供來源驗證；更完整失敗與取消情境仍待擴充。本輪以 FFmpeg 解碼取代獨立 ffprobe 依賴。
- 模型參數、權重白名單與完整來源前處理串接仍待遠端實作。
- 尚未部署到公網或私人伺服器；已有依範圍拆分的本機 Git commit，尚未 push。對照見工作日誌 W009。

## 下一個接手者

1. 讀 AGENTS、README、06 任務、07 決策及 11 遠端契約。
2. T028／T029 的額外版本 checkbox 已完成；T016 來源實測已完成。下一步仍為 T025 的來源失敗／取消整合，模型主機就緒後接上 separate／extra_exports 契約。
3. 為真實環境補上下載中取消、總時長與大小限制的整合測試。
4. 依 LOCAL-MODEL-001 接續單機試用，再做真實歌曲端到端及正式音質驗證。
5. 再進行 T011–T015／T017 的音質、權重許可與效能驗證；不要把本機環境當遠端基線。
6. 遠端接入前先保持 loopback，透過受控私人通道，不直接公開一般管理 API。
7. 每完成一個小任務，按改動範圍驗證並更新相關任務、證據與接手紀錄，立即自行 commit；不等整輪結束。

## 主要程式入口

API：music_stem_lab/app.py；工作狀態：store.py；檔案：artifacts.py。
本機執行器：local_worker.py；來源：download_task.py；備份：maintenance.py。
網頁：music_stem_lab/static/；測試：tests/；瀏覽器驗證：scripts/browser-smoke.mjs。

機密／執行資料：data/、.venv/、.tmp/、models/、.env* 已排除 Git。
ENV-001 保留舊機快照，ENV-002 記錄本次新機評估。產品、架構與舊技術說明若有差異，以本輪 D010 及 11 文件為準。


## 輸出與 DAW 說明

見 [分軌輸出與 DAW](12-OUTPUTS-AND-DAW.md)。音軌為模型類別的 WAV，非 DAW 專案或 MIDI；separate 原生軌／選填伴奏契約已實作，單機 GPU 已通過合成來源的產物驗證。
