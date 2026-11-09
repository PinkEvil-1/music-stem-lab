# Music Stem Lab：規格與接手入口

更新：2026-11-09。網站與本機 GPU 分軌已接通，單機試用方式見 README。

先閱讀 [README](README.md) 啟動網站。示範模式只產生合成測試音，可驗證排隊、檔案發布、試聽與下載，不代表音樂分離已完成。

## 接手順序

1. [Agent 規則](AGENTS.md)。
2. [接手狀態](docs/00-HANDOFF.md)：最新階段、執行方式與下一步。
3. [任務追蹤](docs/06-TASKS.md) 與 [決策](docs/07-DECISIONS.md)。
4. [遠端 worker 契約](docs/11-REMOTE-WORKER.md)：本輪跨機邊界與實際行為。
5. [本機驗證證據](docs/evidence/LOCAL-001.md)。
6. 依任務閱讀 [需求](docs/01-PRODUCT-SPEC.md)、[可行性](docs/02-FEASIBILITY.md)、[設計](docs/03-TECHNICAL-DESIGN.md)、[流程](docs/04-WORKFLOWS.md) 與 [驗收](docs/05-VALIDATION-PLAN.md)。

## 文件狀態

01–05 保存完整目標與尚待完成的驗收；11 文件說明本輪已落地的範圍及差異。
[10 技術說明](docs/10-TECHNOLOGY-EXPLAINER.md) 為先前說明，CPU baseline 的順序已被使用者本輪決定取代。
[來源](docs/08-SOURCES.md)、[日誌](docs/09-WORKLOG.md) 與 [模板](docs/templates/EXPERIMENT.md) 保留可回查證據。

所有需求、決策、任務與交接資訊採 UTF-8 純文字保存；程式與測試可納入 Git。
音訊、資料庫、模型、秘密設定與本機測試暫存不可提交 Git。
