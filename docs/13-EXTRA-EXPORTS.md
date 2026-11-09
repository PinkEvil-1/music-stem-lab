# 額外伴奏輸出契約

日期：2026-11-09。依據：D014。需求：R003、R004、R009、R014，驗收 A017。
階段：後端與網頁 checkbox 已完成並驗證，詳見 evidence/EXPORTS-001.md；真實模型與混音仍延後。

## 使用語意

模型分軌保存所有原生 stems。no_vocals、no_guitar 是選填的衍生伴奏，不增加模型原生軌數。
兩項預設不選，可任意組合；雙選各產生一個伴奏，不產生「同時去人聲及去吉他」的第三個檔案。
未勾選的版本不生成、不上傳、不列為必要產物。選項變更屬不同工作輸入，不可重用同一 idempotency_key。
download_audio 不接受額外伴奏；舊 remove_vocals／remove_guitar 保留原本輸出契約，確保歷史工作相容。

## 批次與工作資料

POST /api/jobs/batch 新增 mode=separate 及 extra_exports。
extra_exports 為陣列，可包含 no_vocals、no_guitar，預設 []，儲存前去重並排序。
同批工作共用本次勾選；每筆工作、重試、worker claim 與 manifest 皆保留此欄位。

範例請求：

~~~json
{
  "urls": ["https://youtu.be/EXAMPLE0001"],
  "mode": "separate",
  "execution_kind": "real",
  "extra_exports": ["no_vocals", "no_guitar"],
  "idempotency_key": "example-extra-exports"
}
~~~

## 遠端模型能力

worker claim 的 modes 可包含 separate，另提供 native_stems，列出該次鎖定模型／權重的原生類別。
音軌名稱須為小寫英文字母開頭，後接英數字與底線，最長 64 字元、至多 32 類且不可重複。
source、manifest、no_vocals、no_guitar 為系統保留名稱，不能假稱模型原生軌。

separate 工作必須有非空 native_stems 才能領取。
要求 no_vocals 時需含 vocals，要求 no_guitar 時需含 guitar；不符合則留在 FIFO 前端等待相容 worker，不跳過或自動忽略使用者選項。
未要求額外版本時不強迫模型提供相應類別；仍遵循 D013 的模型原生輸出範圍。

領取後的 native_stems 會寫入 job 與 attempt 快照；這是受控 worker 宣告的能力，不代表模型品質已驗證。
必要音訊為 source＋全部 native_stems＋extra_exports。發布時不允許缺檔或額外夾帶未勾選版本。
manifest 保存 native_stems 與 extra_exports；不放任何驗證 token。

## 資料庫相容性

SQLite schema 升至 user_version=2。
jobs 新增 extra_exports 與 native_stems；attempts 新增 native_stems，預設均為 JSON []。
採加欄位升級，不刪除舊工作或修改已完成的 manifest；既有三種模式的 idempotency payload 維持相容。
應先停止服務再切換程式版本；原有維護工具仍可備份及還原。

## 示範與驗證

合成示範宣告固定六類 native_stems，只是測試資料，實際模型可宣告不同類別與數量。
新增測試覆蓋四種選項組合、原生軌保留、未選產物拒收、缺檔、能力不足、請求去重、重試保存與 v1 資料升級。
真正的伴奏混音計算仍由之後另一台電腦的模型執行器完成，這一輪沒有執行模型。
