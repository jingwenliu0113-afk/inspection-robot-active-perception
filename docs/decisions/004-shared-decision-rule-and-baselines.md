# 004 — Shared decision rule、early-stop 協定與四個 baseline 的定義

- **日期**：2026-10-10
- **狀態**：結構凍結；數值參數為 v0，將在 train / val 上調整並於正式 test 前另開 decision log 凍結
- **是否在看過正式結果後才新增 / 修改**：否。

## 問題

SPEC 比較的是 viewpoint policy。若每個方法各自決定何時說 present / absent，結果就混入了決策門檻差異。需要一條所有方法共用、只用部署資訊的 decision rule，並定義何時停止。

## Shared decision rule（`decision-v0`）

輸入：觀測歷史（detections、viewpoint 幾何、深度推得的 `zone_visible_fraction`）。

- `c_max` = 所有觀測中最高 detector confidence。
- coverage = 「有效觀測」所涵蓋的 azimuth sector 數 / 6；有效觀測 = `zone_visible_fraction ≥ 0.5`（zone 大部分未被擋）。
- `present` 若 `c_max ≥ τ_present (0.6)`，confidence = `c_max`。
- `absent` 若 coverage ≥ 0.5 且 `c_max < τ_absent (0.3)`，confidence = coverage × (1 − c_max)。
- 否則 `inconclusive`。

性質：單一視角沒偵測到永遠是 `inconclusive`（coverage = 1/6），被擋住的視角不算 coverage，弱偵測會阻止 `absent`。`tests/test_decision.py` 驗證。

`zone_visible_fraction` 的來源：synthetic world 由幾何直接算；Gazebo world 將由 depth image 對 zone 取樣點的深度比對計算。它是部署時可取得的感測器量，不是 object occlusion GT。

## Harness 協定（所有方法相同）

1. 觀測初始視角（算第 1 個 view）。
2. 套用 decision rule；若 definitive（present / absent）或 budget 用完就停。
3. 否則 policy 選一個未訪候選，teleport、觀測，回到 2。policy 可回傳 None 提前停止。

## 四個方法

| Policy | 定義 | 可用資訊 |
|---|---|---|
| Single View | 永不移動 | 初始觀測 |
| Random NBV | 在未訪候選中均勻隨機，seed = f(run_seed, episode_id) | 候選集合 |
| Rule-based NBV v0 | score = 1.0·novelty + 1.0·attraction + 0.5·unobstructed；取最高分，平手取最小 id | 見下 |
| Oracle NBV | 物件存在：選 GT visibility 最高的候選；absent：選 GT 未被擋且落在新 sector 的候選 | simulator GT（僅 upper bound） |

Rule-based NBV v0 的三個特徵全部來自 SPEC §6 允許清單：

- novelty：與最近已訪 viewpoint 的角距 / π（viewpoint 幾何、coverage proxy）。
- attraction：若最強偵測為弱偵測（confidence ≥ 0.15 但未達 τ_present），偏好與該視角相距約 45°（σ 30°）的候選（detector confidence + 觀測歷史）。
- unobstructed：以已訪視角的 `zone_visible_fraction` 做角距核加權平均（σ 40°），沒有鄰居時取先驗 0.5（觀測推得的遮擋 proxy）。

不使用：object GT pose、GT visibility、occlusion GT、未來 viewpoint 的真實 detector 結果。`tests/test_leakage.py` 以 tripwire world 驗證 Single / Random / Rule 在整個 run 中從未呼叫 `ground_truth`。

## 參數凍結程序

1. pilot（synthetic 以外，在 Gazebo）確認三狀態可分、teleport deterministic。
2. 在 **train / val** split 上調整 `τ_present, τ_absent, min_coverage, n_sectors` 與 rule-NBV 權重。
3. 正式 test 前另開 decision log 記錄最終值與版本號（`decision-v1`、`rule-nbv-v1`），之後不得更動。
4. 看過 test 結果後若要改規則，只能以新版本在新一輪 test 上報告，並保留舊結果。

## 被凍結的項目

decision rule 的結構（三個條件與其順序）、early-stop 協定、Random 的 seeding 方式、Oracle 的定義、rule-NBV 允許的特徵集合。數值參數尚未凍結（v0）。
