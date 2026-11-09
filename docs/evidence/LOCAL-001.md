# LOCAL-001：本機網站與工作協調器驗證

日期：2026-11-09。對應 T019–T025，需求 R001、R005–R008、R011–R013。
模型推論與音質：DEFERRED／NOT_RUN。真實來源下載已另完成，見 SOURCE-001.md；本文件記錄本機合成與控制面測試。

## 環境

Windows 10 x64；Python 3.13.17；Node.js 24.21.0。
FastAPI 0.162.2、Starlette 1.10.0、Pydantic 2.14.3、Uvicorn 0.54.0。
pytest 9.2.0、httpx 0.28.1、yt-dlp 2026.10.26。
另安裝 imageio-ffmpeg 0.8.1，所附 FFmpeg 回報 9.0.2-essentials_build-www.gyan.dev。
完整依賴已鎖於 requirements.lock；pip check 回報 No broken requirements found。
安裝僅在專案 .venv，未安裝 CUDA、PyTorch、Demucs 或模型。

## 自動測試

最終結果：42 passed，1 warning，62.56 秒。較早的 39 項回歸亦通過；新增實際 FFmpeg 解碼後已完整重跑。
警告為 Starlette TestClient 對 httpx 的棄用提醒，測試仍通過；未將棄用提醒當作失敗或隱藏。
首次執行因測試暫存父目錄缺少而產生 19 個 setup error；建立專案 .tmp 後重新執行。
新增備份、服務鎖及上傳限制後，完整回歸得到以上最終結果。

執行：
.venv/Scripts/python.exe -m pytest -q --basetemp <專案內唯一測試目錄> --tb=short

測試素材為 EXAMPLE0001 等假影片 ID 與一秒合成 PCM WAV，不連線下載音樂。
涵蓋：
- A001／A002：網址白名單、正規化、批次部分成功、非法輸入。
- A007／A015：FIFO、雙 Store 競爭、前方模式不支援時不插隊、重送去重、重試排尾。
- A008／A010：過期租約、人工恢復、舊 token 拒絕、取消等待 ACK、取消與發布競態。
- A006：更名後資料庫提交前中斷恢復、跨 app 實例保存資料、損毀偵測。
- A011：尚未發布不可下載、完成產物、Range 206、下載附件與 manifest。
- A014：配額不足、上傳大小、執行中拒刪、tombstone 恢復、備份還原。
- A016 的本機子集：Host／Origin、worker token、錯誤不回顯輸入、路徑限制。
- 示範明確標記 simulated=true，驗證不啟動下載子程序。
- yt-dlp adapter 以替身測試參數與原始音檔流程；不代表真實 YouTube 驗收。

## 追加 FFmpeg 實測

以實際 FFmpeg 將一秒合成 WAV 編成 WebM／Opus，再經上傳 API 實際解碼、核對約一秒時長並完成發布。另測偽造 WebM 拒絕、二秒來源超過一秒限制時拒絕，以及解碼取消 checkpoint。這三項新增測試納入最終 42 項回歸。沒有下載任何音樂。

## 真實瀏覽器

執行：node scripts/browser-smoke.mjs。
結果：PASS，7 項檢查：
server_http、browser_submit_two_jobs、demo_fifo_completion、artifact_dialog、audio_range、
mobile_no_overflow、no_browser_errors。

使用現有 Edge、新的獨立 user-data-dir、獨立測試資料及本機動態埠。
確認兩筆示範工作完成、詳情顯示三個音訊播放器、Range 回 206。
桌機視窗 1440×1100、手機視窗 390×844；手機沒有水平溢出。
已人工檢視桌機與手機截圖，文字、表單及操作列表可見。
第一輪偵測網站圖示 404；補上本機 SVG favicon 後重新驗證通過。
瀏覽器與測試服務已在 finally 結束；未操作個人瀏覽器設定檔或對外部署。

本機截圖（屬 .gitignore 排除的可重建暫存）：
- .tmp/browser-1794213446136/desktop.png
- .tmp/browser-1794213446136/mobile.png
- .tmp/browser-1794213446136/result.json

## 驗證限制

- A003 完整解碼與實際時長核驗子集已測；使用者提供來源的真實下載另見 SOURCE-001.md，不能外推所有來源。
- A004／A005／A012、Q001–Q006 模型相關驗收皆未執行。
- A008 已以本機故障注入測試，不是跨機斷網／長音訊推論演練。
- A016 沒有涵蓋公開部署或多使用者身分驗證；服務保持 loopback。
- FFmpeg 解碼已整合；單一真實來源另有通過證據，更多網路／格式變化仍待驗證。
- 備份還原測試使用合成資料；正式資料還原演練與跨 OS 還原未執行。
- 測試與瀏覽器 PASS 不代表可以恢復錄音室原始分軌或已通過音質門檻。
