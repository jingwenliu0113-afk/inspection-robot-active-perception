# 011 — v2：設計、資料使用與評估協定（預先登錄）

- **日期**：2026-10-13
- **狀態**：協定凍結；調參結果另以 decision 012 凍結，holdout 結果以 decision 013 報告
- **是否在看過正式結果後才新增 / 修改**：**是——v2 是看過 v1 test 結果（decision 010）之後提出的改進。**
  因此本檔明定：v1 的 test split **不得**用於 v2 的設計、調參或驗證；任何 v2 改善宣稱只能來自本檔新增、未參與開發的 holdout 資料。

## 1. 使用者決定（2026-10-13）

1. 暫不進入 Advanced B（Nav2），先完善研究結果。
2. 開發 v2，重點修正「未觀察區域被當成 absent」的問題，合理使用 `inconclusive`。
3. GitHub 維持 private，不新增 LICENSE。
4. 完整保留 v1 的程式、結果與失敗紀錄；不得放寬 Gate 或改寫原始結果；v1 / v2 分開報告。

## 2. 保留 v1（不變更）

- `results/test-v1/`、decision 001–010、`activeperception/frozen.py`（v1 參數）、`DecisionRule` / `RuleNBVPolicy` / `OracleNBVPolicy` 的 v1 行為一律不改。
- v2 以**新增**的類別與參數實作；`Observation` 只新增欄位（v1 程式不讀）。
- 回歸檢查：v1 在 val 上的 stage-3 數字與 pilot 報告必須逐位元重現（tests 涵蓋）。**不在原 test 上重跑 v1**（decision 009 的 test 只跑一次）。

## 3. 問題（來自 v1 已公開的失敗紀錄）

- `decision-v1` 的 absent 條件是「≥ 2 / 8 扇區有 zone 可見 ≥ 30% 的視角」——一個**代理指標**，並未確認 zone 中每個可能放置物件的位置都被看過。
  test 上 Random 在 `core-g0103-v0` 出現 false absent：兩個視角的 zone 大致可見，但消防栓所在位置一直沒被看到。
- `rule-nbv-v1` 的可見度預測把未觀測格子當成空的（樂觀），`core-g0298` 因此選到被「藏在柱子後面的柱子」擋住的視角。

## 4. v2 設計

### 4.1 `decision-v2`（四個方法共用，結構改變）

**候選位置**：zone 內物件可能站立的位置，以 sunflower 取樣 24 個點，半徑 `zone.radius − r_obj`（`r_obj = 0.2 m`，目標類別的尺寸先驗，部署時已知）。
每個位置一根「假想物件軸線」：高度 zone.height × {1/6, 1/2, 5/6} 三點。

**位置被某視角「看穿」（cleared）**：該視角的 depth 中，軸線點在視野內且量測深度 ≥ 該點深度 − 0.05 m 的比例 ≥ `col_min`。
也就是相機的視線**穿過**該位置一路沒被擋——這是「看見空的空間」的正面證據，不是「沒偵測到」。
若物件真的站在該位置，軸線點在物件內部，depth 會先打到物件表面 → 該位置**不可能**被看穿；
候選位置間距約 11 cm、小於消防栓本體直徑，因此物件存在時至少有一個位置永遠無法被看穿。

**規則**：

- `present`：`c_max ≥ tau_present`（同 v1），confidence = `c_max`。
- `absent`：所有視角聯集後被看穿的位置比例 `cleared ≥ tau_clear`，且 `c_max < tau_absent`；confidence = `cleared × (1 − c_max)`。
- 其餘 `inconclusive`。

`tau_clear = 1.0` 時，absent 等於「zone 內每個可能位置都被確認為空」。

### 4.2 `rule-nbv-v2`

- 已知地圖：由走訪視角的 depth 障礙物格（同 v1）＋ 每個視角的 2D 可見扇形（視野內、第一個障礙物之前的格子）組成「已知空」區域；其餘為**未知**。
- `clear_gain`（主特徵）：對每個尚未看穿的位置，預測候選相機的 2D 視線：經過已知障礙 → 0；全程已知空 → 1；經過未知 → `p_unknown`（`p_unknown = 1` 即 v1 的樂觀假設，`0` 為悲觀）。取平均。
- 其他特徵：novelty、attraction（同 v1 定義）、v1 的 predicted zone visibility（可被調為 0）。
- 全部只用部署時可得的資訊（depth、detections、幾何）；沒有 GT。

### 4.3 `oracle-v2`（上限）

物件存在：選 GT 可見度最高的候選（同 v1）。物件不存在：選**實際**能看穿最多尚未看穿位置的候選（讀取該候選尚未觀測的 depth，即未來觀測，僅 oracle 可用），平手取 novelty。

## 5. 資料使用

| 資料 | v1 用途 | v2 用途 |
|---|---|---|
| `core` train | 調參 | **調參**（開發資料） |
| `core` val | 檢查 | **檢查**（開發資料） |
| `core` test | v1 正式 test（已封存） | **不使用**（只引用 v1 已公開的失敗紀錄作為動機） |
| `pilot` | pilot | pilot 管線檢查、ROS 2 線上一致性 |
| **`holdout`（新）** | — | **v1 與 v2 的正式比較**，只跑一次 |

`holdout`：新 namespace（獨立 seed 流）、`gen-v2` world、**150 scene groups × 4 = 600 episodes，全部屬於新的 `holdout` split**。本檔 commit 之後才產生。
程式強制：調參工具拒絕 `test` 與 `holdout`；v2 設定拒絕在 `test` 上執行。

## 6. 調參協定（只用 train；val 只檢查）

### 階段 1：`decision-v2`

- 觀測：Random NBV（seeds 0–4），budgets {2, 3, 5}。
- 網格：`tau_present` ∈ {0.5, 0.7}；`tau_absent` ∈ {0.02, 0.05}；`tau_clear` ∈ {0.9, 0.95, 1.0}；`col_min` ∈ {2/3, 1}（24 組）。
- 限制：false-absent = 0、**geometric false-absent risk = 0**、false-present ≤ 1%。
  geometric false-absent risk：物件存在、結束時 `cleared ≥ tau_clear`、但走訪的每個視角 GT 可見度都 < 0.1——即「物件沒被看到卻滿足 absent 的幾何條件」，不依賴 detector 是否剛好漏看。
- 目標：平均 accuracy 最大；**平手容忍 0.01**，平手時依序偏好 `tau_clear` 大、`col_min` 大、`tau_absent` 小、`tau_present` 大（保守）。

### 階段 2：`rule-nbv-v2`

- `decision-v2` 固定。網格：`w_gain` ∈ {0, 1, 2}、`p_unknown` ∈ {0, 0.25, 0.5, 1}、`w_novelty` ∈ {0, 0.25, 0.5}、`w_attraction` ∈ {0, 0.5}、`w_visibility_v1` ∈ {0, 0.5}。
- budgets {2, 3, 5}；限制：false-absent ≤ Random（v2）、geometric false-absent risk = 0。
- 目標：平均 accuracy 最大；平手（0.005）偏好非零權重少、平均視角少、`p_unknown` 小。

### 階段 3：val 檢查

四個方法 × budget 1–8，v1 與 v2 並列；不再調參。

## 7. Holdout 協定（decision 012 凍結後，只跑一次）

- 三組設定，各含 Single / Random（seeds 0–4）/ Rule / Oracle，budgets {1, 2, 3, 5}（正式）＋ 1–8 曲線：
  1. **v1**：`decision-v1` + `rule-nbv-v1` + oracle-v1（凍結值不變）
  2. **v2**：`decision-v2` + `rule-nbv-v2` + oracle-v2
  3. **消融**：`decision-v2` + `rule-nbv-v1`（區分改善來自判定規則還是視角策略；只報告 Rule 一列）
- 統計：同 decision 009（scene-group cluster bootstrap，1000 次，成對差異）。

### 預先登錄的宣稱與判定

| 宣稱 | 判定方式（holdout） |
|---|---|
| S（安全） | v2 每個方法的 false-absent rate ≤ 同方法的 v1；且 v2 的 Rule、Oracle false-absent = 0 |
| A（Rule 準確率） | v2 Rule − v1 Rule 的 accuracy 成對差異：CI 下界 > 0 才宣稱「改善」；CI 下界 > −0.02 為「不劣於」；否則如實報告「變差」 |
| F（失敗型態） | Rule 的「浪費視角」比例（非初始視角且沒有看穿任何新位置）v2 < v1，報告差異與 CI |
| Gate | decision 009 §4 的判準**原樣**套用於 v2（不放寬）；v1 在 holdout 上同樣套用（v1 結論的獨立重現） |

v1 原 test 結果（decision 010）保持原樣；README 分開呈現 v1 test、v1 holdout、v2 holdout。
