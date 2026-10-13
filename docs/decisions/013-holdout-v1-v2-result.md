# 013 — Holdout：v1 與 v2 的正式比較結果

- **日期**：2026-10-13
- **狀態**：已判定
- **是否在看過正式結果後才新增 / 修改**：是——本檔記錄 holdout 結果，依 decision 011 §7 / 012 預先登錄的宣稱與 Gate 判定；
  沒有修改任何參數、指標或判準。decision 010（v1 原 test）維持原樣，不改寫。

## 執行

- `python -m activeperception.experiment_v2 holdout ...`（一次），commit `e450414`，工作目錄乾淨（`git_dirty = false`）。
- `holdout` split：新 namespace、150 scene groups、600 episodes（visible 122 / unobservable 178 / absent 300），在 decision 011 之後產生，未參與任何開發。
- detector `detector-v1`（RTX 5070 Ti、GPU lock 下產生快取，7800 frames）。輸出：`results/holdout/`。
- 同一批 episodes、同一份觀測，跑三組凍結設定：v1（原封不動的 v1 程式路徑）、v2、消融（`decision-v2` + `rule-nbv-v1`）。

## 結果（accuracy，95% scene-group cluster bootstrap CI）

| budget | v1 Single | v1 Random | v1 Rule | v1 Oracle | v2 Single | v2 Random | **v2 Rule** | v2 Oracle |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.210 | 0.210 | 0.210 | 0.210 | 0.392 | 0.392 | 0.392 | 0.392 |
| 2 | 0.210 | 0.608 | 0.683 [0.637, 0.728] | 0.712 | 0.392 | 0.868 | **0.957 [0.930, 0.980]** | 1.000 |
| 3 | 0.210 | 0.898 | 0.968 [0.945, 0.988] | 1.000 | 0.392 | 0.975 | **0.998 [0.995, 1.000]** | 1.000 |
| 5 | 0.210 | 0.997 | 1.000 | 1.000 | 0.392 | 0.998 | **1.000** | 1.000 |

false-absent：v1 Random 0.0007（seeds 平均），其餘全部 0；v2 **所有方法、所有 budget 皆 0**。geometric false-absent risk：v1、v2 皆 0。
false-present：全部 0。ECE（definitive decisions）：v1 多視角方法 0.21–0.38；**v2 全部 ≤ 0.008**。

## 預先登錄的宣稱（decision 011 §7）

| 宣稱 | 結果 | 判定 |
|---|---|---|
| S 安全 | v2 每個方法的 false-absent ≤ v1；v2 Rule / Oracle = 0 | **成立** |
| A Rule 準確率（v2 − v1） | budget 2：+0.273 [0.228, 0.317]；budget 3：+0.030 [0.010, 0.052] | **兩個 budget 都是「改善」**（CI 下界 > 0） |
| F 浪費視角比例（v2 − v1） | budget 2：0.011 vs 0.287（−0.276 [−0.344, −0.215]）；budget 3：0.010 vs 0.434；budget 5：0.010 vs 0.445 | **成立**（注意：「浪費」以 v2 的看穿標準定義，對 v2 有利，只作輔助） |

### 消融：改善來自哪裡

| | budget 2 | budget 3 |
|---|---|---|
| 判定規則效果（消融 Rule − v1 Rule） | **+0.253 [0.215, 0.293]** | +0.025 [0.010, 0.043] |
| 策略效果（v2 Rule − 消融 Rule） | +0.020 [−0.020, 0.058] | +0.005 [−0.003, 0.020] |

**v2 的改善幾乎全部來自 `decision-v2`（以 depth 看穿每個候選位置作為 absent 的正面證據）；
`rule-nbv-v2` 的未知空間建模相對於 `rule-nbv-v1` 沒有統計上顯著的額外貢獻。** 如實報告，不宣稱策略本身有改善。

## Gate（decision 009 §4 判準原樣套用）

| | v1（holdout，獨立重現） | v2（holdout） |
|---|---|---|
| 1. Rule 穩定勝過 Random / Single（budget 2、3） | 成立：rule − random +0.075 [0.054, 0.094]、+0.070 [0.050, 0.090] | 成立：+0.089 [0.058, 0.114]、+0.023 [0.015, 0.031] |
| 2. 非 leakage | 成立（tests，含 v2 tripwire） | 成立 |
| 3. 可重現殘餘失敗 | 209 件 | 27 件（11 scene groups），全部是 `inconclusive`，沒有錯誤的肯定答案 |
| 4. Rule 接近 Oracle | **否**：oracle − rule = +0.028 [0.012, 0.048]（b2）、+0.032 [0.012, 0.055]（b3） | **budget 2 否**：+0.043 [0.020, 0.070]；budget 3 是（+0.0017 [0, 0.005]） |

### 誠實揭露

1. **v1 在原 test 上「接近 Oracle」的結論沒有在 holdout 重現**（差距 0.028–0.032，超過預先登錄的 0.02 門檻，CI 不含 0）。
   decision 010 的原始紀錄不改；原 test 的 0.004 應視為偏樂觀的單次估計。
2. **v2 Rule 在 budget 2 與 Oracle 仍有 4.3 個百分點差距**，可歸因於視角選擇（Oracle 用未來觀測挑第二個視角；detector 與導航不是原因）。
   依 SPEC，「Rule 已接近 Oracle → 不需要 RL」這個停止條件在 budget 2 **不成立**；是否進 Advanced（C：RL，或 B：Nav2）仍需使用者決定，不自動啟動。
3. v2 下 Single View 的 accuracy 上升（0.21 → 0.39），來自「初始視角就能看穿全部候選位置」時的正面空間證據，不是把「沒偵測到」當 absent。

## v2 殘餘失敗（budget 2 / 3，27 件）

- budget 2 absent → inconclusive（17）：兩個視角後看穿比例 0–0.98；Oracle 能找到一次看穿全部的第二視角。
- budget 2 unobservable → inconclusive（9）：第二視角只看到消防栓一部分（數件有 0.35–0.45 的弱偵測，低於 τ_present 0.7）；budget 3 時全部判對。
- budget 3 absent → inconclusive（1）：`holdout-g0058-v1`，三個視角後看穿 84%。
