# Music Stem Lab

個人使用的音樂工作室：批次貼上 YouTube 網址、依序排隊、管理處理狀態，並試聽及下載產物。模型會在另一台受控電腦執行，本機網站不需要安裝 GPU、CUDA 或 PyTorch。

目前已實作網站與工作協調器，真實模型分離及音質驗收依使用者指示延後。

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
| 去人聲／去吉他／多樂器分軌 | 模型實作與品質驗證延後 |

去吉他草案指一般吉他全部合併移除，保留人聲與 bass。逐把吉他分離仍是研究項目。

## 本機啟動

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

真實去人聲／去吉他工作可先排入佇列，等待另一台電腦接入。佇列嚴格依序；第一筆尚無可用執行器時，後面的示範或下載工作也會等待。可取消該筆後繼續。

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
