# Music Stem Lab

個人使用的音樂工作室：批次貼上 YouTube 網址、依序排隊、管理處理狀態，並試聽及下載產物。單機試用可在同一台電腦啟用 NVIDIA GPU 分軌。

網站、工作協調器與本機 CUDA 分軌已接通。實際歌曲的音質驗收待完成。

## 目前可以做什麼

| 功能 | 狀態 |
| --- | --- |
| 單筆／批次網址驗證與正規化 | 已實作 |
| SQLite 持久化 FIFO、重送去重、分頁與篩選 | 已實作 |
| 取消、失敗重試排尾端、失聯工作人工恢復 | 已實作 |
| 檔案驗證、manifest、原子發布、試聽與 Range 下載 | 已實作 |
| 儲存配額、刪除與中斷清理、離線備份還原 | 已實作 |
| 合成音示範流程 | 已實作；不下載歌曲、不執行分軌 |
| 僅下載音訊 | 已實作；提供來源的真實下載、解碼與保存驗收通過 |
| 遠端 worker 領取、心跳與檔案回傳 API | 已實作並以測試驗證；跨機連線待驗證 |
| 模型原生軌與額外伴奏選項 | 後端與網頁 checkbox 已完成，四種組合及合成示範已驗證；本機 GPU 模式已接通 |
| 去人聲／去吉他／多樂器分軌 | 本機 Demucs 六軌已用合成來源通過整合驗證，正式音質待驗證 |

分軌種類與軌數依所選模型／權重實際提供的能力，不固定要求四軌或六軌，也不額外拆分同類樂器。去人聲與去吉他仍為必要目標；吉他以模型提供的 guitar 類別整體處理。

## 本機啟動

Windows 已備妥環境時，雙擊根目錄的 `Start Music Stem Lab.cmd`。它會啟動 127.0.0.1:8000 的 GPU 工作室，確認就緒後開啟預設瀏覽器。若服務已啟動，會直接開啟頁面。

保留標題為「Music Stem Lab」的啟動視窗。關閉這個 CMD 視窗會停止本機服務及其分軌子程序，執行中的工作會中斷。若要保留這次處理結果，請等工作完成後再關視窗。排隊中的工作會保留。

在工作管理員的「詳細資料」可找 `cmd.exe` 和 `python.exe`。啟用「命令列」欄後，以 `-m music_stem_lab` 辨識服務，以 `-m scripts.start_local` 辨識啟動器。

雙擊 Start 會先檢查 Python、網站套件、CUDA 套件與六軌權重。出現中文提示時，輸入 `Y` 並按 Enter 開始建置，輸入 `N` 取消。缺少 Python 時可先用 WinGet 安裝 Python 3.13。需要支援 CUDA 的 NVIDIA 顯示卡與可用驅動程式。已有完整環境會直接驗證並啟動。

整體百分比按建置階段更新。pip 顯示各套件的下載進度，模型權重以已收到的位元組更新百分比，通過 SHA-256 才會保存。已有離線 wheel 備份時會優先使用。下載中斷可重開 Start 重試。

預設讀取 `.venv/Scripts/python.exe` 與 `models/5c90dfd2-34c22ccb.th`。若使用其他位置，可在專案根目錄建立 `.env.local.json`，設定 `python` 和 `checkpoint` 兩個路徑字串。相對路徑從專案根目錄解析。啟動日誌在 `.tmp/local-launch.log`。

網站選擇「模型分軌」後，可選快速、均衡（預設）或精細。三組均使用 Demucs htdemucs_6s。網頁會顯示所用顯卡、當下可用與總 VRAM、系統 RAM，並以綠字或紅字比較預設建議。

| 預設 | 分段／重疊／時移次數 | 建議可用 VRAM／RAM |
| --- | --- | --- |
| 快速 | 4 秒／25%／1 次 | 3／4 GiB |
| 均衡 | 6 秒／25%／3 次 | 5／6 GiB |
| 精細 | 7 秒／50%／5 次 | 7／8 GiB |

建議值是操作參考，記憶體占用與處理時間會隨音訊和當下負載而變動。所選預設會跟隨工作保存，實際執行設定可在產物的處理紀錄查閱。

若已備妥 `models/wheels/environment.lock` 和其中列出的 wheel，可用相同版本與架構的 Python 離線重建環境。此電腦的備份對應 Windows x64、Python 3.13 與 CUDA 版 PyTorch。

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links models/wheels -r models/wheels/environment.lock
~~~

已完成的工作會顯示「開啟結果資料夾」，直接在 Windows 檔案總管開啟該筆產物所在資料夾。手動啟動時可加 `--enable-local-folder` 啟用。

目前已在 Windows、Python 3.13.17 驗證網站部分。以下命令都在專案根目錄執行。

初次建立環境：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip --isolated install -r requirements.lock
~~~

啟動網站：

~~~powershell
.\.venv\Scripts\python.exe -m music_stem_lab
~~~

開啟 http://127.0.0.1:8000 。服務僅監聽本機；Ctrl+C 停止。
Linux／macOS 的 Python 路徑改為 .venv/bin/python，這些平台尚未實測。

點「填入示範網址」，確認已勾選「使用示範流程」，再提交工作，即可體驗排隊、完成、試聽及下載。示範使用一秒合成測試音，所有工作及 manifest 都標記為 demo。

選「模型分軌」時，原生音軌都會保留；可獨立勾選「去人聲版本」及「去吉他版本」額外輸出，預設皆不勾。雙選會產生兩個伴奏檔，僅下載模式不提供這兩項。

PCM WAV 可直接用一般播放器播放，網站也提供 audio 播放器；本輪已以合成 PCM WAV 驗證瀏覽器播放，單機 CUDA 也已產生合成來源的模型 WAV。

啟用本機模型需在同一 Python 環境安裝支援顯示卡的 PyTorch CUDA、相符的 TorchAudio、Demucs 4.0.1 與 SoundFile。試用已驗證 PyTorch／TorchAudio 2.8.0+cu128。從上游取得 [官方六軌權重](https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th)，並指定本機檔案。

~~~powershell
.\.venv\Scripts\python.exe -m music_stem_lab --enable-download --model-checkpoint "C:\path\to\5c90dfd2-34c22ccb.th"
~~~

開啟 http://127.0.0.1:8000 ，確認頁面顯示本機 GPU 分軌已啟用。貼上有權使用的 YouTube 網址，選模型分軌並提交。啟動時驗證固定權重 SHA-256 和 CUDA。未配置模型時，真實分軌工作會等待執行器。

本機新產物與下載使用「分軌類型 - YouTube 影片名稱」，例如「吉他 - 歌名.wav」。檔名會去除不支援的字元，缺少標題時使用影片 ID。

## 僅下載音訊

需要啟用本機來源下載時，使用：

~~~powershell
.\.venv\Scripts\python.exe -m music_stem_lab --enable-download
~~~

選「僅下載音訊」，並取消示範勾選。adapter 透過 yt-dlp 取得原始音訊格式，不轉成 MP3，也不做分軌。來源須符合相關權利及平台允許的使用方式。

下載有時長、大小、磁碟與逾時限制，不使用瀏覽器 cookie 或登入資料。FFmpeg 由 imageio-ffmpeg 套件提供，下載後會實際解碼並檢查時長；WAV 另核對 PCM 規格及完整 frames。解碼驗證已用合成音實測，並已完成使用者提供來源的真實 YouTube 下載驗收。這個版本使用 FFmpeg 完整解碼，不另依賴 ffprobe。

## 組成與資料

| 檔案／目錄 | 責任 |
| --- | --- |
| music_stem_lab/app.py | FastAPI、工作與遠端 worker API、下載及本機存取限制 |
| music_stem_lab/store.py | SQLite、交易領取、FIFO、租約及狀態紀錄 |
| music_stem_lab/artifacts.py | 音檔驗證、雜湊、發布、恢復與刪除 |
| music_stem_lab/local_worker.py | 合成示範與可選來源下載執行器 |
| music_stem_lab/download_task.py | 隔離子程序中的 yt-dlp adapter |
| music_stem_lab/decode.py | FFmpeg 來源解碼、實際時長限制與取消 |
| music_stem_lab/maintenance.py | 單一服務鎖、離線備份及還原 |
| music_stem_lab/static/ | HTML、CSS、JavaScript，無前端建置步驟 |
| tests/ | 使用假網址與合成音訊的自動測試 |
| scripts/browser-smoke.mjs | 獨立瀏覽器設定檔的實際網頁驗證 |
| requirements.lock | 本次驗證的完整依賴版本，包含測試套件 |
| data/ | 執行時資料，已由 .gitignore 排除 |

預設限制為每批 20 筆、單片 20 分鐘、單檔 500 MiB、資料配額 20 GiB、磁碟至少保留 1 GiB。這些是目前程式預設，之後仍需依正式環境實測調整。

可用 MUSIC_STEM_DATA_DIR 指定資料目錄。遠端 worker 驗證使用 MUSIC_STEM_WORKER_TOKEN；未設定時 worker API 關閉。一般網站介面設計為本機使用，不應直接改成公網服務。跨機接入先使用受控私人通道，詳見 [遠端契約](docs/11-REMOTE-WORKER.md)。

## 測試與維護

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check music_stem_lab/static/app.js
node scripts/browser-smoke.mjs
~~~

瀏覽器測試需 Node.js 22 以上與已安裝的 Edge／Chrome，使用全新設定檔及獨立測試資料，不讀取個人瀏覽器資料。截圖與測試資料放在已忽略的 .tmp/。

停止網站，且沒有 running／publishing／recovering 工作後，可備份：

~~~powershell
.\.venv\Scripts\python.exe -m music_stem_lab.maintenance backup --data-dir data --output backups/snapshot-001
~~~

備份需放在資料目錄之外；還原目標必須不存在或為空：

~~~powershell
.\.venv\Scripts\python.exe -m music_stem_lab.maintenance restore --snapshot backups/snapshot-001 --data-dir restored-data
~~~

備份包含一致的 SQLite 快照、已發布音檔及雜湊；不包含未發布暫存、模型或秘密設定。備份可能含個人音訊資料，請保存在本機，不加入 Git。

目前的驗證結果與限制見 [本機驗證報告](docs/evidence/LOCAL-001.md) 與 [真實來源報告](docs/evidence/SOURCE-001.md)。預設資料已保留這次完成的真實來源工作，啟動網站後即可查看及試聽。模型測試通過前，不把網站示範完成當作音源分離成功。

## 規格與 Agent 接手入口

採需求 ID → 驗收案例 → 任務 → 實作 → 驗證證據 → 更新狀態的方式開發。

| 要查的內容 | 文件 |
| --- | --- |
| 閱讀順序 | [START_HERE.md](START_HERE.md) |
| Agent 工作規則 | [AGENTS.md](AGENTS.md) |
| 當前狀態、阻礙與下一步 | [接手狀態](docs/00-HANDOFF.md) |
| 功能範圍 | [產品規格](docs/01-PRODUCT-SPEC.md) |
| 吉他案例與模型限制 | [可行性分析](docs/02-FEASIBILITY.md) |
| 架構與工作語意 | [技術設計](docs/03-TECHNICAL-DESIGN.md)、[工作流程](docs/04-WORKFLOWS.md) |
| 音質與系統驗收標準 | [驗證計畫](docs/05-VALIDATION-PLAN.md) |
| 已完成／待完成任務 | [任務追蹤](docs/06-TASKS.md) |
| 決策、來源與歷次工作 | [決策](docs/07-DECISIONS.md)、[來源](docs/08-SOURCES.md)、[日誌](docs/09-WORKLOG.md) |
| 跨機 worker 介面 | [遠端契約](docs/11-REMOTE-WORKER.md) |

規格中尚未實作的部分仍標為草案；目前行為以程式與驗證證據為準。
