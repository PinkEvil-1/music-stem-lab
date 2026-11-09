---
title: GPU 推論與 Music Stem Lab 技術方案
lang: zh-Hant
template: doc
---
GPU 推論是用顯示卡執行已訓練好的分軌模型。
目前建議採 Python、FastAPI、SQLite 與獨立 worker。
模型先以 CPU 驗證，再評估 GPU 加速。

## A 推論是什麼？

訓練是用大量資料，讓模型學會分辨音源。
推論是把新音樂交給已訓練好的模型，取得分軌估計。
本專案先使用現成權重，不自行訓練。

例如：輸入一首混合人聲、鼓與吉他的歌曲。
模型推論後，輸出各類音源的估計訊號。
再混合非吉他音源，或比較相減方法，製作去吉他伴奏。

分軌不是識別檔名，也不是單純調整 EQ。
輸出仍會有殘留與誤傷，需要案例驗證。
[Demucs 模型與使用說明](https://github.com/facebookresearch/demucs)

## B CPU 與 GPU 差在哪裡？

| 項目 | CPU 推論 | GPU 推論 |
| --- | --- | --- |
| 執行位置 | 中央處理器 | 顯示卡 |
| 工作記憶體 | 主要使用系統 RAM | 模型與中間運算需要 VRAM |
| 運算方式 | 可平行運算 | 擅長大量規則相似的張量運算 |
| 相容性 | 仍需支援的軟體組合 | 還需核對顯卡、驅動與運算後端 |
| 本專案用途 | 先建立可重現 baseline | 相容且記憶體足夠時評估加速 |

PyTorch 是執行模型運算的框架。
對 NVIDIA GPU，常用 CUDA 作為運算後端。
CPU 與 GPU 是執行裝置，模型才定義分軌方法。
[PyTorch CUDA 說明](https://docs.pytorch.org/docs/stable/notes/cuda.html)

GPU 不是自動提高音質的開關。
速度優勢依模型、資料與硬體而定。
同模型跨裝置也不保證逐位元一致。

## C 你的電腦適合怎麼開始？

目前盤點：i7-8700、約 32 GB RAM、GTX 1050 2 GB VRAM。
盤點當下只剩約 802 MiB VRAM，會隨其他程式變動。

建議先建立 CPU 執行環境，驗證模型載入與音質。
接著量測處理時間與記憶體，再決定是否測試 GPU。
這是候選路徑，尚未成功載入或執行模型。

系統 RAM 與 VRAM 分開計算。
32 GB RAM 不等於顯示卡有 32 GB 可供模型使用。
換較強 GPU 也不能直接宣稱每把吉他都能分開。

## D 打算用什麼技術？

以下是本輪建議，尚未選定套件版本或完成相容性驗證。

| 層次 | 建議技術 | 作用與理由 |
| --- | --- | --- |
| 網站介面 | HTML、CSS、JavaScript | 網址輸入、模式選擇、排隊列表及音訊播放；先維持簡單 |
| 網站 API | Python＋FastAPI | 接收工作、查詢狀態、取消及提供下載 |
| 工作資料庫 | SQLite | 保存工作順序、狀態、重試與產物索引；適合個人單機起步 |
| 背景執行器 | 獨立 Python worker 程序 | 從資料庫逐筆領取工作，管理耗時計算與重啟恢復 |
| 來源取得 | yt-dlp 候選 adapter | 取得平台允許且具適當權利的音訊；需另驗證可用性 |
| 解碼與匯出 | FFmpeg／ffprobe | 解碼、檢查音訊、轉格式及產生試聽檔 |
| 模型執行 | PyTorch | 在 CPU 或相容 GPU 上執行模型 |
| 分離模型 | Demucs baseline | 去人聲先評估 htdemucs；吉他先評估 htdemucs_6s |
| 檔案保存 | 本地磁碟＋manifest.json | 保存音檔、權重版本、參數與產物資訊 |

Demucs 六軌候選含 guitar 與 piano。
它是比較基準，不是已選定的最終模型。
上游原 repository 已封存，需評估依賴與維護風險。
品質不合格時，再評估其他模型及權重。
[Demucs 官方 repository](https://github.com/facebookresearch/demucs)

耗時分離放在獨立 worker，不放進網站請求。
API 回應入列結果後，頁面持續查詢狀態。
SQLite 工作紀錄負責持久化；程序退出後才有恢復依據。
這是本專案設計，並非 FastAPI 自動提供完整持久化佇列。
[FastAPI 對重型背景工作的說明](https://fastapi.tiangolo.com/tutorial/background-tasks/)

## E 一筆工作如何執行？

```flow
網頁 -> FastAPI: 提交網址與模式
FastAPI -> SQLite: 保存排隊工作
SQLite -> Python工作程序: 依序領取
Python工作程序 -> 音訊取得與解碼: yt-dlp與FFmpeg
音訊取得與解碼 -> PyTorch分軌: CPU或相容GPU
PyTorch分軌 -> 檔案儲存: 驗證與發布
```

網頁透過 API 查詢進度、試聽與下載。
CPU／GPU 只影響其中模型計算部分的執行方式。
即使更換推論裝置，網址表單與工作契約仍可沿用。

## F 為什麼先選這個組合？

主要候選模型使用 Python，可減少跨語言整合工作。
單人逐筆處理先用 SQLite 與單 worker，維持較少部署元件。
目前沒有必要先引入 Redis、Celery 或分散式服務。

.NET API 也能搭配 Python worker，並非不可行。
若偏好 C#，可在定案前比較額外程序通訊與維護成本。
目前推薦 Python 是基於模型生態與個人使用規模。

下一步是 T011：核對完整依賴、權重許可與測試素材。
先確認可執行與可驗證，再承諾速度及分離品質。
