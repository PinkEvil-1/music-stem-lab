# LOCAL-MODEL-003：三組本機分軌預設

日期：2026-11-11。狀態：PASS（流程與音訊規格）。
對應 T040、R009、A011／A012／A017。

## 環境與來源

Windows、Python 3.13、PyTorch 2.8.0+cu128、RTX 2070 SUPER 8 GiB。使用固定 htdemucs_6s 權重，SHA-256 由 `model_task` 啟動時驗證。輸入為本機產生的 8 秒靜音 WAV，44.1 kHz、雙聲道、PCM 16 位元。

## 執行與結果

以 `python -m music_stem_lab.model_task <權重> --preset <fast|balanced|detailed> --source <輸入> --target <輸出> --kinds vocals guitar --rate 44100 --frames 352800 --channels 2` 分別執行。三組皆輸出人聲及吉他 WAV，兩個檔案都符合 352800 取樣幀、44.1 kHz、雙聲道。測試套件另驗證 API、保存的選項、執行參數與 manifest。

音質比較、長曲耗時與峰值記憶體為 NOT_RUN。
