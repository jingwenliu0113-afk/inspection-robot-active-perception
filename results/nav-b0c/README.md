# decision 016 確認批次（`nav-b0c`，新資料，只跑一次）

- 資料：新 namespace `nav-b0c`（decision 016 凍結後才產生），6 scene groups × 2 variants，流程同 B0（每集 12 個候選 + 2 次中途取消，168 個停點 + 12 個初始視角）。
- 執行：`OUT=runs/nav-b0c ./docker/nav_b0.sh 3 …`（commit `af89a24`），12 / 12 集第一次完成；分析 commit `1a973b2`（只多記錄 git commit）。
- `b0_report.json`：`decision_016` 區塊為 decision 016 的可部署路徑；`criteria` / `decisions` 為 B0 原路徑（AMCL 估計位姿），作對照。

| decision 016 §4 | 結果 | 判定 |
|---|---|---|
| R1：錯誤肯定答案 = 0、geometric risk（初始 + 任一停點）= 0 | 0 / 168、0 / 168 | **通過** |
| R2：所有停點聯集 geometric risk = 0 | 0 / 6（同一批資料的 AMCL 原路徑：**3 / 6 不安全**） | **通過** |
| R3：C1–C5 仍成立 | C1、C2（RTF 0.998）、C4（p95 7.2 cm / 0.037 rad）、C5（真實位姿 depth 誤差 0.25 mm）通過；**C3 86.1%（124 / 144）< 90%** | **未通過** |
| R4：精修品質與準確率代價 | 精修成功 170 / 180，位置誤差 p50 0.25 cm、p95 0.32 cm（最大 2.2 cm）、朝向 p95 0.0005 rad；組合 absent → absent 61 / 84（AMCL 路徑相同，沒有代價）；所有停點聯集 absent 5 / 6（1 集因 detector 弱誤報 0.022 > τ_absent 0.02 而 inconclusive，安全方向） | 報告 |

## C3 未通過的組成

20 次未準確到點：18 次只是真實朝向誤差 0.100–0.116 rad（門檻 0.10），1 次位置 0.101 m，1 次 Nav2 回報失敗（0.162 m）。
Nav2 依 AMCL 估計判定到點（容忍 0.07 m / 0.05 rad），到點當下 AMCL 的朝向誤差約 0.05 rad，兩者相加約 0.10；之後 AMCL 自行修正，所以拍攝時記錄的定位誤差看起來很小。
判定使用精修位姿（誤差 p95 0.32 cm），所以這不影響安全，只代表實際視角與規劃的候選視角相差約 0.1 rad。

判定：依 decision 016 §4，R3 未成立 → **不進 B1，詢問使用者。**
