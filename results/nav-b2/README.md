# B2：Nav2 正式評估（`nav-b2`，decision 018 預先登錄，只跑一次）

- 資料：新 namespace `nav-b2`（split `nav-eval`），40 scene groups × 4 variants = 160 episodes（absent 80、unobservable 38、visible 42），decision 018 commit 之後產生。
- 執行：Single、Rule-NBV v2、Oracle v2（seed 0）、Random seeds 0–2，每個一個 `inspection-ap-navdet` 容器、budget 5 → **960 次閉迴路執行**（`./docker/nav_b1.sh 4 nav-b2`，commit `4955086`）。
  980 次嘗試：20 次是啟動看門狗（Nav2 180 s 未就緒）退出後重試成功；其中 2 個工作第一輪兩次都失敗，由續跑腳本重跑後成功。期間 Docker 沒有中斷。
- teleport 對照：同場景 Core 流程 render + Core harness replay（凍結 v2、精確位姿）。
- 分析：`uv run python -m activeperception.nav.b1_analysis --ns nav-b2 --out results/nav-b2`（`b1_report.json`、`tables.md`）。
- 統計：scene-group cluster bootstrap 1000 次（seed 0）；Random 先在 3 個 seeds 上平均。

![teleport vs Nav2](../../docs/figures/nav_teleport_vs_nav2.png)

### Accuracy

| 方法 | budget 1 | 2 | 3 | 5 |
|---|---|---|---|---|
| Single（teleport / Nav2） | 0.525 / 0.525 | 0.525 / 0.525 | 0.525 / 0.525 | 0.525 / 0.525 |
| Random（teleport / Nav2） | 0.525 / 0.525 | 0.908 / 0.902 | 0.981 / 0.983 | 1.000 / 1.000 |
| Rule-NBV v2（teleport / Nav2） | 0.525 / 0.525 | 0.988 / 0.981 | 1.000 / 1.000 | 1.000 / 1.000 |
| Oracle v2（teleport / Nav2） | 0.525 / 0.525 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |

### Q1 安全（Nav2，budget 1–5 合計）

| 方法 | false absent | false present | geometric risk |
|---|---|---|---|
| single | 0 | 0 | 0 |
| random | 0 | 0 | 0 |
| rule | 0 | 0 | 0 |
| oracle | 0 | 0 | 0 |

### Q2 Nav2 − teleport（accuracy）

| 方法 | budget 2 | budget 3 |
|---|---|---|
| single | +0.000 [+0.000, +0.000] non-inferior | +0.000 [+0.000, +0.000] non-inferior |
| random | -0.006 [-0.015, +0.000] non-inferior | +0.002 [+0.000, +0.006] non-inferior |
| rule | -0.006 [-0.019, +0.000] non-inferior | +0.000 [+0.000, +0.000] non-inferior |
| oracle | +0.000 [+0.000, +0.000] non-inferior | +0.000 [+0.000, +0.000] non-inferior |

### Q3 主動視角（Nav2）

| 比較（Nav2） | budget 2 | budget 3 |
|---|---|---|
| Rule − single | +0.456 [+0.306, +0.613] holds | +0.475 [+0.325, +0.650] holds |
| Rule − random | +0.079 [+0.044, +0.119] holds | +0.017 [+0.004, +0.033] holds |

### Q4 成本（每個 episode）

- 行走距離：Rule 1.61 m、Random 2.08 m；差 -0.463 [-0.797, -0.143] m
- 導航時間（模擬）：Rule 10.9 s、Random 13.5 s；差 -2.646 [-4.496, -0.748] s

### 導航（SPEC Advanced B 指標）

- 導航次數 440；準確到點（path success / reachable viewpoint）1.000；Nav2 回報成功 440；碰撞 0；逾時 0；進入 zone 0
- 每次導航延遲（模擬，含重定位）p50 22.1 s、p95 28.4 s；重定位修正次數 {'0': 18, '1': 15, '2': 407}；精修失敗 5

## 判定（decision 018 §3）

| 問題 | 結果 | 判定 |
|---|---|---|
| Q1 安全 | Nav2 下所有方法、所有 budget：false absent 0、false present 0、geometric risk 0 | **成立** |
| Q2 導航造成的變化 | 四個方法、budget 2 / 3 的 Nav2 − teleport 皆在 −0.006 以內，CI 下界 ≥ −0.019 | **四個方法皆不劣於 teleport** |
| Q3 主動視角在 Nav2 下 | Rule − Single +0.456 / +0.475；Rule − Random +0.079 / +0.017（CI 下界皆 > 0） | **成立** |
| Q4 成本 | Rule 每集少走 0.46 m [0.14, 0.80]、少 2.6 s [0.7, 4.5]（模擬時間） | 報告 |

描述性（未預先登錄）：Nav2 下 Oracle − Rule 在 budget 2 為 0.019、budget 3 為 0。
