# SOURCE-001：使用者提供來源的真實下載驗證

日期：2026-11-09。任務：T016。對應 R002、R005、R011 與 A003／A006／A011 的真實來源路徑。
結果：PASS（單一提供來源）。沒有執行模型或音源分離。

## 來源與範圍

使用者回覆下載實測詢問時，提供影片 ID GhNRdavqXW0。
使用者提供的分享參數已去除，adapter 僅使用正規化網址：
https://www.youtube.com/watch?v=GhNRdavqXW0

此紀錄保存測試授權來源，不自行推定其他影片或其他使用方式也有相同許可。

## 實際執行

命令：.venv/Scripts/python.exe scripts/source-smoke.py --url <正規化來源網址>
設定：enable_download=true、execution_kind=real、mode=download_audio。
原始測試資料目錄：data/source-20261109T084859Z，已排除 Git。

狀態依序觀察到 queued → running/fetching → running/decoding → completed。
產物為來源音訊與 coordinator 生成的 manifest，沒有合成音取代真實來源。

## 結果

| 項目 | 結果 |
| --- | --- |
| 工作 ID | a2b798957d9f47108770de38dd4e6e93 |
| 來源格式 | audio/webm |
| 檔案大小 | 3,913,692 bytes（約 3.73 MiB） |
| FFmpeg 實際解碼時長 | 253.5386875 秒（約 4 分 14 秒） |
| 解碼驗證 | ffmpeg_decode，驗證取樣率 16 kHz |
| FFmpeg 版本 | 9.0.2-essentials_build-www.gyan.dev |
| manifest.simulated | false |
| 音訊 Range | HTTP 206 |
| 模型／GPU | 未使用 |

## 預設工作室匯入

確認 data/jobs.sqlite3 與 data/jobs 尚不存在後，以 SQLite backup API 複製測試資料庫，並複製已發布工作目錄到預設 data。
未覆寫既有資料。匯入後重新啟動 app，已確認 completed 歷史與來源 Range 206 可讀。

預設來源檔：
data/jobs/a2b798957d9f47108770de38dd4e6e93/attempts/18011545f803408bb585f67074b29821/published/source-4cf5de939474428cabb966b0dbcec3c3.webm

一般啟動命令即可在工作列表看到此次完成工作：
.venv/Scripts/python.exe -m music_stem_lab
原測試目錄仍保留作驗證證據，沒有自動刪除。
音檔、資料庫及原始測試 JSON 不納入 Git；本文件只保存驗收結果。

## 限制與後續

單一影片成功不代表所有 YouTube 來源永遠可用。
尚未對真實受限／私人影片、網路中斷及長時間下載取消做實機驗證。
界限、非法輸入、取消、故障及租約已有本機自動測試；完整跨機情境另待遠端整合。
去人聲、去吉他、各樂器軌、音質與 GPU 效能皆未驗證。
