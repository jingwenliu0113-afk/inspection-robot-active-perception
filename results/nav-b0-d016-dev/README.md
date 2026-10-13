# decision 016 開發評估（`nav-b0`，開發資料）

同一批 B0 影像（`runs/nav-b0`），改用 decision 016 的可部署路徑：depth 對設施地圖位姿精修（`nav-pose-v1`）+ 看穿判定的位姿餘裕（`nav-margin-v1`）。
這份是**開發資料**上的結果（參數就是在這批資料上選的），不是驗證；驗證只來自之後的新資料 `nav-b0c`（`results/nav-b0c/`）。

`b0_report.json` 的 `decision_016` 區塊：

| 項目 | B0（AMCL 估計位姿） | decision 016 |
|---|---|---|
| 位姿誤差 p50 / p95 | 4.1 cm / 7.6 cm；0.022 / 0.039 rad | 精修成功 164 / 180：0.26 cm / 0.74 cm（最大 2.15 cm）；0.0002 / 0.0025 rad |
| 錯誤肯定答案（168 組） | 0 | 0 |
| geometric risk（初始 + 任一停點） | 1 / 168 | **0 / 168** |
| 所有停點聯集 geometric risk | 2 / 6 | **0 / 6**（物件存在時聯集看穿 87.5–93.8%） |
| absent → absent（組合） | 64 / 84 | 64 / 84（沒有準確率代價） |
| absent episode 所有停點聯集 | 6 / 6 absent | 6 / 6 absent |

精修退化（只看到一面牆或柱面）16 / 180：goal 6、cancel 10、初始 0；這些停點改用 AMCL 估計加寬餘裕（0.10 m / 0.06 rad）。
