# decision 016 第二次確認（`nav-b0d`，新資料，只跑一次；使用者指示「再試一次」）

- 修正：停點視角重定位 `nav-relocalize-v1`（decision 016 附錄 C）；其餘設定與標準不變。
- 資料：新 namespace `nav-b0d`（附錄 C commit 之後產生），6 scene groups × 2 variants；12 / 12 集第一次完成（commit `76e431d`）。
  第一次啟動因 `specs_by_id` 漏了新 namespace，每集都在 `prepare` 階段失敗，沒有產生任何資料（`runs/nav-b0d-attempts-failed-prepare.log`）。

| 標準 | 結果 | 判定 |
|---|---|---|
| C1 相容性 | 12 / 12 | 通過 |
| C2 RTF | 0.999 | 通過 |
| C3 準確到點 ≥ 90%、碰撞 0 | **144 / 144 = 100%**；到點誤差 p95 5.7 cm / 0.049 rad；碰撞 0、進入 zone 0、最小間隙 0.20 m | 通過 |
| C4 定位 p95 | **0.42 cm / 0.0021 rad**（重定位後的 AMCL） | 通過 |
| C5 觀察可靠性 | 新影像 180 / 180；真實位姿 depth 誤差 0.25 mm；偵測 ≥ 10k px 57 / 57、< 5k px 0 / 32；absent 最高 confidence 0.0075 | 通過 |
| C6 / R1 | 錯誤答案 0 / 168；geometric risk 0 / 168 | 通過 |
| R2 | 所有停點聯集 geometric risk 0 / 6（物件存在時聯集看穿 85.9–90.6%） | 通過 |

R4（報告）：精修成功 170 / 180（退化：goal 1、cancel 9），誤差 p95 0.31 cm / 0.0009 rad。重定位：144 個目標中 131 個修正 2 次、8 個 1 次、5 個不需修正。
**準確率代價**：「初始 + 一個停點」組合中 absent → absent 為 47 / 84（只用重定位後 AMCL 位姿、無餘裕時為 54 / 84）——
餘裕讓 7 組變成 `inconclusive`（安全方向）；所有停點聯集時 absent 仍 6 / 6。

判定：**B0 全部通過 → 依 decision 016 §4 進 B1（decision 017）。**
