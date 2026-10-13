# B1：閉迴路 Nav2 整合（`nav-b1`，開發資料，decision 017）

- 資料：`nav-b1`（`Split.NAV_DEV`），4 scene groups × 4 variants = 16 episodes（absent 8、unobservable 2、visible 6）。
- 執行：每個（episode、方法、seed）一個 `inspection-ap-navdet` 容器：Single、Rule-NBV v2、Oracle v2、Random seeds 0–2 → 96 次執行（`./docker/nav_b1.sh 3 nav-b1`）。
- teleport 對照：同場景以 Core 流程 render（`renders/nav-b1`）、Core harness replay 同樣方法。
- 分析：`uv run python -m activeperception.nav.b1_analysis --ns nav-b1 --out results/nav-b1` → `b1_report.json`。
- **開發資料，只用來確認管線；樣本太小（unobservable 只有 2 集），不是研究結果。**

| | budget 1 | 2 | 3 | 5 |
|---|---|---|---|---|
| Single teleport / Nav2 | 0.750 / 0.750 | 0.750 / 0.750 | 0.750 / 0.750 | 0.750 / 0.750 |
| Random teleport / Nav2 | 0.750 / 0.750 | 0.938 / 0.875 | 0.979 / 0.958 | 1.000 / 1.000 |
| Rule teleport / Nav2 | 0.750 / 0.750 | 0.750 / 0.750 | 1.000 / 1.000 | 1.000 / 1.000 |
| Oracle teleport / Nav2 | 0.750 / 0.750 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |

- 所有方法、所有 budget：false absent 0、false present 0、geometric risk 0。
- 導航 32 次：準確到點 32 / 32、碰撞 0、逾時 0、進入 zone 0；每次導航（含重定位）模擬時間中位數 24 s；每次導航行走距離 Rule 3.6 m、Random 4.1 m、Oracle 5.3 m。
- Nav2 與 teleport 的差異只出現在 Random（budget 2 有 3 件 teleport 答對、Nav2 為 `inconclusive`）。

## 整合中發現並修正的工程問題（不影響已完成的執行）

1. 同一 episode 的多個工作並行時共用同一份場景檔，可能讀到寫到一半的檔案；1 次 Gazebo 啟動失敗（exit 255）很可能由此造成，
   而 `BasicNavigator` 會無限等待。修正：每個工作寫自己的場景目錄；Nav2 180 s 內沒有就緒就退出並重試。
   成功的執行都讀到完整檔案（不完整的 XML / 地圖會直接失敗，不會悄悄改變場景）。
2. 工作改為動態佇列（原本靜態分配，最後只剩 1 個 worker）。
