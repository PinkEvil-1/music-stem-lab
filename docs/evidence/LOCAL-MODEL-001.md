# LOCAL-MODEL-001：單機 GPU 試用驗證

日期：2026-11-09（Asia/Taipei）。對應 T031，需求 R002–R009、R011、R014。
驗收：A004／A005 的產物部分、A006、A011／A012 的類別與檔案部分、A017 的單機接入。
狀態：單機 CUDA 與發布 PASS，實際歌曲端到端與音質 NOT_RUN。

## 環境與來源

Windows 10、Python 3.13.17、RTX 2070 SUPER、PyTorch 2.8.0+cu128、TorchAudio 2.8.0+cu128、Demucs 4.0.1。權重雜湊、CUDA 盤點見 ENV-002。
以 FFmpeg 生成八秒雙聲道 WebM／Opus 合成音，測試中只替換下載入口。真實佇列、解碼、CUDA 推論、WAV 伴奏、manifest 與下載均執行。
模型採 4 秒分段、25% 重疊、shifts=0；伴奏由其餘音軌相加，共用防削波增益。

## 結果

- 真實工作模式，無勾選時發布來源、六個原生 WAV、manifest，共八件。雙選時另外發布兩個 WAV，共十件。
- 核對 manifest 的模式、選項、模型及權重 SHA-256。逐軌以 Range 206 讀取 WAV 標頭，確認下載回傳 attachment。
- pytest：60 項通過。已知 Starlette TestClient 的 httpx 棄用提醒一項。
- Edge：既有 10 項瀏覽器 smoke 通過，包含示範送單、獨立勾選、WAV 實際播放與 Range。
- 第一輪發現 Windows 長測試路徑與儲存掃描競態。將暫存根縮短，並讓掃描略過剛消失的 SQLite sidecar 或中間檔後重跑通過。
- YouTube 下載 adapter 的先前單一來源證據見 SOURCE-001。本輪未重新使用該影片。
- 真實歌曲音質、長曲、取消與失敗情境的完整驗收仍待執行。
