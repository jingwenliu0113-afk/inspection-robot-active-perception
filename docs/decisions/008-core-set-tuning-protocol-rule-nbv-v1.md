# 008 — 正式 episode set、調參協定（預先登錄）與 rule-NBV v1 設計

- **日期**：2026-10-13
- **狀態**：協定凍結；調參結果與最終參數另開 decision 009 記錄（看 test 之前）
- **是否在看過正式結果後才新增 / 修改**：否。寫於任何 `core` episode 跑過任何 policy 之前。

## 1. 正式 episode set

- namespace `core`、generator `gen-v2`、world `sdf-world-v2`、image `sha256:49d6e69b…`、detector `detector-v1`。
- **300 scene groups × 4 variants = 1200 episodes**，split 依 decision 002（40 / 20 / 40，以 scene group 為單位）。
- 凍結檔：`data/episodes/specs-core.json`（render 輸入）、`data/episodes/gazebo-core.json`（specs + GT，render 後產生）。
- 理由：test 約 120 groups / 480 episodes；四個方法在同一批 episodes 上成對比較，cluster bootstrap（以 scene group 為 cluster）的差異 CI 約 ±3–5 個百分點。render 約 25 分鐘、0.8 GB，成本低。

## 2. 調參協定

**原則**：只在 `train` 調參，`val` 只用來檢查（過擬合、回歸），`test` 在 decision 009 凍結前完全不跑任何 policy。
程式強制：調參工具拒絕 `test` split。

### 階段 1：shared decision rule → `decision-v1`

- 觀測來源：**Random NBV**（run seeds 0–4），budgets {3, 5}。用 baseline 的觀測調門檻，不讓 decision rule 偏向 rule-NBV；這對「rule 勝過 random」的主張是保守的。
- 搜尋空間：
  - `tau_present` ∈ {0.3, 0.4, 0.5, 0.6, 0.7}
  - `tau_absent` ∈ {0.05, 0.1, 0.2, 0.3}，且 `tau_absent ≤ tau_present`
  - `n_sectors` ∈ {4, 6, 8}；`min_coverage` 以「至少 k 個有效扇區」表示，k ∈ {2, 3, 4}（`min_coverage = k / n_sectors`，k < n_sectors）
  - `effective_zone_fraction` ∈ {0.3, 0.5, 0.7}
- 目標：train 上平均 accuracy（Random@3、Random@5，5 個 seeds 平均）最大，
  限制 **false-absent rate = 0** 且 false-present rate ≤ 1%（兩個 budget、所有 seeds）。
- 平手（accuracy 差 ≤ 0.005）時依序偏好：k / n_sectors 較大（absent 較保守）、`tau_present` 較大、`effective_zone_fraction` 較大。

### 階段 2：rule-NBV → `rule-nbv-v1`

- decision rule 固定為 `decision-v1`。在 train 上調權重，budgets {3, 5}（rule-NBV 是決定性的，單一 run）。
- 目標：平均 accuracy 最大，限制 false-absent rate 不得高於同 budget 的 Random NBV（train）。
- 平手（≤ 0.005）時偏好非零權重較少者（較簡單），再偏好平均使用視角數較少者。

### 階段 3：val 檢查

在 val 上對四個方法跑 budget 1–8，報 accuracy / false-absent / inconclusive / avg viewpoints。
val 不再調參；若 val 顯示嚴重問題（例如 rule-NBV 在 val 明顯差於 random），只能另開 decision log 修改設計並重跑階段 1–3。

### 凍結（decision 009）

最終參數、版本號（`decision-v1`、`rule-nbv-v1`）與**正式 budget 組合**。SPEC §8 例示 {1, 3, 5}；
budget 最終值屬研究設計決策，**由使用者確認**（附 val 的 success-vs-budget 曲線）。之後才跑 test。

## 3. rule-NBV v1 的特徵（全部屬於 SPEC §6 允許清單）

| 特徵 | 定義 | SPEC §6 對應 |
|---|---|---|
| coverage gain | 候選所在扇區（與 decision rule 相同的扇區劃分）尚未有「有效視角」時為 1 | viewpoint geometry + coverage proxy |
| predicted zone visibility | 由**已觀測 depth 影像**累積 zone 外障礙物高度圖（5 cm 格、地面與 zone 圓柱內排除），預測候選相機到 zone 取樣點的視線比例；未觀測格子視為空（樂觀） | observation history（感測器資料）+ coverage proxy |
| novelty | 與最近已訪視角的角距 / π（同 v0） | viewpoint geometry |
| attraction | 最強偵測為弱偵測（≥ `tau_weak` 且未達 `tau_present`）時，偏好與該視角相距約 45° 的候選（同 v0） | detector confidence + observation history |
| unobstructed（v0） | 已訪鄰近視角的 `zone_visible_fraction` 核加權平均（同 v0；可被調為 0） | observation-derived occlusion proxy |

score = Σ wᵢ · featureᵢ，取最高分，平手取最小 id。

**不使用**：object GT pose、GT visibility、occlusion GT、simulator semantic labels、未來視角的真實 detector 結果。
障礙物高度圖只來自走訪過視角的 depth（部署時深度相機本來就提供），zone 圓柱內的點（包含目標本身）一律排除。
`tests/test_leakage.py` 的 tripwire 涵蓋 v1。

`Observation` 新增 `obstacle_cells`（可雜湊的 (ix, iy, 高度 cm) tuple），由 depth 計算；synthetic world 以解析幾何近似。

## 被凍結的項目

core set 規模與檔案、三階段調參協定（資料、目標、限制、平手規則、搜尋空間）、rule-NBV v1 的特徵集合與定義。
