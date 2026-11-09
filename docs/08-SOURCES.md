# 外部查證來源

查閱日期：2026-11-09。以下是一次資料查證快照；實作前應重查維護狀態、依賴版本及授權。
僅查詢公開技術資訊；未傳送 repository、設定、日誌或音訊至外部。

| ID | 來源 | 支持的結論 |
| --- | --- | --- |
| S001 | https://github.com/facebookresearch/demucs | 六軌候選含 guitar／piano；可做去人聲；獨立 rescale 影響相對音量；原 repository 已封存 |
| S002 | https://github.com/ZFTurbo/Music-Source-Separation-Training | 支援多種分離架構及推論／訓練流程；權重能力須另外確認 |
| S003 | https://github.com/yt-dlp/yt-dlp | 音訊取得與後處理依賴；完整 YouTube 支援涉及額外 JS 執行環境等依賴 |
| S004 | https://arxiv.org/abs/2507.01172 | 古典雙吉他同音色分離研究；證明是可研究的特定問題，不證明一般歌曲可靠逐把分離 |
| S005 | https://www.youtube.com/static?template=terms | 平台對下載與自動存取有許可限制；不能只檢查音樂權利 |

## 查證限制

- 沒有下載任何模型或權重，不代表任何候選權重已通過授權檢查。
- 沒有在本機驗證依賴相容性或下載器可用性。
- 沒有量測任何音質、效能、VRAM 或成功率。
- 多吉他合併移除是基於類別輸出語意的工程推論；需 C004–C006 實測。
- Python／SQLite 等架構是個人規模的工程提案，並非已從程式碼確認的現況。
