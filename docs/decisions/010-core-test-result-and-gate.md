# 010 — Core 正式 test 結果與 Gate 判定

- **日期**：2026-10-13
- **狀態**：已判定（Core v1 結束）
- **是否在看過正式結果後才新增 / 修改**：**是**——本檔記錄 test 結果與依 decision 009 預先登錄判準所做的判定；
  沒有修改任何 success definition、budget、split、metric 或參數。

## Test 執行

- `python -m activeperception.experiment test ...`（一次），commit `3dd52b9`，工作目錄乾淨（`git_dirty = false`）。
- `core` test split：131 scene groups、524 episodes（visible 105 / unobservable 157 / absent 262）。
- 版本：`gen-v2`、`label-v1`、`detector-v1`（FRCNN-MobileNetV3）、`decision-v1`、`rule-nbv-v1`；Random NBV 為 seeds 0–4 平均。
- 完整輸出：`results/test-v1/report.json`、`results/test-v1/outcomes.jsonl`；摘要：`results/test-v1/README.md`。

## 主要結果（accuracy，95% cluster bootstrap CI）

| budget | Single | Random | Rule-NBV v1 | Oracle |
|---|---|---|---|---|
| 1 | 0.202 [0.160, 0.246] | 0.202 | 0.202 | 0.202 |
| 2 | 0.202 | 0.620 [0.580, 0.661] | **0.706 [0.664, 0.748]** | 0.710 [0.670, 0.752] |
| 3 | 0.202 | 0.907 [0.890, 0.924] | **0.996 [0.989, 1.000]** | 1.000 |
| 5 | 0.202 | 0.998 [0.996, 1.000] | **1.000** | 1.000 |

成對差異（同一組 bootstrap 重抽）：

| 比較 | budget 2 | budget 3 |
|---|---|---|
| rule − random（accuracy） | +0.086 [0.072, 0.101] | +0.089 [0.069, 0.108] |
| rule − random（inconclusive） | −0.085 [−0.100, −0.071] | −0.088 [−0.107, −0.068] |
| rule − single（accuracy） | +0.504 [0.492, 0.515] | +0.794 [0.750, 0.834] |
| oracle − rule（accuracy） | +0.004 [0.000, 0.011] | +0.004 [0.000, 0.011] |

false-absent rate：Single / Rule / Oracle 在所有 budget 都是 0；Random 為 0.0015（`core-g0103-v0`，seeds 3、4，budget ≥ 2）。false-present rate：全部為 0。

## Gate（decision 009 §4）

| 判準 | 判定 | 依據 |
|---|---|---|
| 1. Rule 穩定勝過 Random 與 Single | **成立** | budget 2、3 的 rule − random、rule − single accuracy 差異 CI 下界皆 > 0；rule false-absent（0）≤ random（0.0015） |
| 2. 非 candidate leakage | **成立** | 候選視角只依 scene-group seed（`test_leakage.py`）；含 v1 特徵的 GT tripwire 與 replay label tripwire 通過；rule-NBV 只讀 depth / detections / 幾何 |
| 3. 明確、可重現的殘餘失敗 | **成立** | 見下節；replay 為決定性，皆可重現 |
| 4. Rule 是否接近 Oracle | **是** | 每個正式 budget 的 oracle − rule ≤ 0.004，CI 含 0 |

### 殘餘失敗（rule-NBV，budget 2 / 3，共 156 件）

1. **budget 結構限制（152 件，budget 2 的 absent → inconclusive）**：這 152 件的初始視角 zone 可見度皆 < 0.3（不算有效視角），
   budget 2 只剩一個視角，不可能湊滿 `decision-v1` 要求的 2 個有效扇區。Oracle 在 absent 上同樣只有 0.420——這是 budget 與 decision rule 的上限，不是策略錯誤。
2. **未觀測遮擋的樂觀假設（4 件，同一 scene group `core-g0298` 的 4 個 variants）**：初始視角的 depth 只看到前方柱子，
   第二根柱子被擋住；障礙物高度圖把未觀測格子視為空，預測 candidate 4 可見，實際 zone 可見度 0.00 / 0.02，浪費一個視角
   （unobservable 在 budget 2、absent 在 budget 3 因此 inconclusive）。圖：`docs/figures/failure_case.png`。

## 判定與後續

- 依 SPEC Core Gate：「若 rule-based 已接近 oracle，停止，不需要 RL」→ **不啟動 Advanced C（RL）**。
- **Advanced A（detector fine-tuning）不成立**：瓶頸不是 perception——可見像素 ≥ 10k 的 frame 在 τ_present = 0.7 下偵測率 99.8%，visible 狀態四個方法皆 100% 正確；
  失敗全部來自視角選擇與 budget 限制。
- **Advanced B（Nav2）**：Gate 1–3 成立，技術上允許；但 Advanced 不是自動下一步（docs/EXPERIMENT_RULES.md），**需使用者決定**。
- 殘餘失敗 2（未觀測遮擋）若要處理，屬於 rule-NBV v2（例如對未觀測格子採悲觀或機率式假設），只能在新一輪 test 報告，v1 結果保留。

## 誠實揭露的限制

- 此 world 的 perception 偏容易：absent frame 幾乎沒有誤報，detector 選型的主指標因此飽和（decision 005 附錄 B）。
- `decision-v1` 的 absent 規則較寬（2 / 8 扇區、zone 可見 ≥ 0.3）；train / val 沒有 false absent，test 上 Random 出現 1 個 episode（2 個 seeds）。
- definitive decision 的 confidence 校準不佳（ECE 0.21–0.38）：absent 的 confidence 公式為 coverage × (1 − c_max)，覆蓋 0.25 時正確的 absent 也只有 0.25 confidence。結構在 decision 004 凍結，v1 不修改。
- 結果來自 Gazebo 渲染的 replay；ROS 2 線上執行在 pilot 上與 replay 192 / 192 一致（decision 007），test 本身未在線上重跑。
