# 外部查證來源

查閱：2026-11-09。以下為公開技術查詢；未傳送 repository、設定、日誌或音訊至外部。

| ID | 來源 | 用途 |
| --- | --- | --- |
| S001 | https://github.com/facebookresearch/demucs | 去人聲與六軌候選、音量策略及封存維護限制 |
| S002 | https://github.com/ZFTurbo/Music-Source-Separation-Training | 替代分離架構及推論流程候選 |
| S003 | https://github.com/yt-dlp/yt-dlp | 來源下載 adapter 與依賴查證 |
| S004 | https://arxiv.org/abs/2507.01172 | 古典雙吉他同音色分離研究，不外推成通用保證 |
| S005 | https://www.youtube.com/static?template=terms | 平台下載及自動存取的許可條件 |
| S006 | https://pytorch.org/get-started/locally/ | 模型主機之後選擇相容安裝組合 |
| S007 | https://fastapi.tiangolo.com/tutorial/testing/ | API 測試流程；實際相容性由本地測試驗證 |
| S008 | https://github.com/imageio/imageio-ffmpeg | 隔離環境內取得 FFmpeg 執行檔，避免依賴全域 PATH |

## 本地證據與限制

已建立並測試網站／控制面，使用 imageio-ffmpeg 0.8.1 所附 FFmpeg 進行真實編碼／解碼測試，見 evidence/LOCAL-001.md。
未下載或執行模型；未通過任何音質門檻。使用者提供來源的真實 YouTube 下載已通過，見 evidence/SOURCE-001.md。
模型與權重的許可仍須各自查核；程式套件可安裝不代表權重可交付。
