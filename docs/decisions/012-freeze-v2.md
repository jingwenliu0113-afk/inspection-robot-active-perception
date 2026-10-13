# 012 — 凍結 v2（`decision-v2`、`rule-nbv-v2`、`oracle-v2`）

- **日期**：2026-10-13
- **狀態**：**凍結**。寫於 `holdout` split 跑任何 policy 之前；依據只有 core train（調參）與 core val（檢查）。
- **是否在看過正式結果後才新增 / 修改**：v2 整體是看過 v1 test 之後提出的（decision 011）；
  本檔的參數只用 train / val 決定，**未使用 v1 test 或 holdout**。

## 調參結果（decision 011 §6 協定，`results/tuning-v2/`）

### 階段 1：`decision-v2`（train，Random NBV seeds 0–4，budgets {2, 3, 5}）

24 組全部可行（false-absent = 0、geometric false-absent risk = 0、false-present = 0），accuracy 0.948–0.952，全部落在平手容忍 0.01 內；
依保守平手規則選出：

| 參數 | 值 |
|---|---|
| `tau_present` | 0.7 |
| `tau_absent` | 0.02 |
| `tau_clear` | **1.0**（64 個候選位置全部被看穿才可能 absent） |
| `col_min` | 1.0（一個視角中該位置軸線三點全部可見才算看穿） |
| 候選位置 | 64 點、`r_obj` 0.2 m、看穿容忍值 0.03 m（decision 011 附錄 A） |

### 階段 2：`rule-nbv-v2`（train）

144 組全部可行，90 組在最佳值 0.005 內；依平手規則（非零權重最少）選出最簡單者：

| 參數 | 值 |
|---|---|
| `w_gain` | **1.0** |
| `p_unknown` | **0.5**（經過未觀測空間的視線只算一半） |
| `w_novelty`、`w_attraction`、`w_visibility` | 0 |
| 已知空間地圖 | 5 cm 格、zone 周圍 2.5 m、視野射線 4.5 m、障礙物 ≥ 30 cm、候選相機 0.5 m 內視為空 |

train：budget 2 / 3 / 5 accuracy 0.972 / 0.996 / 0.996（同 decision-v2 下 Random 0.871 / 0.979 / 0.995）。

### 階段 3：val 檢查（只報告）

| | budget 2 | budget 3 |
|---|---|---|
| Single（v2 判定） | 0.514 | 0.514 |
| Random（v2 判定） | 0.903 | 0.985 |
| Rule-NBV v2 | 0.995 | 1.000 |
| Oracle v2 | 1.000 | 1.000 |

所有方法、budget 1–8：false-absent = 0、geometric false-absent risk = 0。val 沒有顯示需要修改設計的問題。
（v1 在 val：Single 0.273、Random 0.699 / 0.922、Rule 0.777 / 0.991——兩者判定規則不同，不可直接當成方法改善；正式比較只在 holdout。）

說明：decision-v2 下 Single View 的 accuracy 上升，是因為初始視角若能看穿全部 64 個候選位置，就有「看見 zone 是空的」的正面證據可判 absent——
不是把「沒偵測到」當成 absent（SPEC §2 仍成立）。

## 凍結內容（`activeperception/frozen_v2.py`）

- `decision-v2`、`rule-nbv-v2` 的上述數值；`oracle-v2` 依 decision 011 §4.3。
- detector `detector-v1`、world `gen-v2`、image `sha256:49d6e69b…`、labeling `label-v1` 不變。
- 正式 budgets {1, 2, 3, 5}、曲線 1–8、Random seeds 0–4、bootstrap 1000 次（同 decision 009）。

## Holdout（只跑一次，decision 011 §7）

v1、v2、消融（`decision-v2` + `rule-nbv-v1`）三組設定；宣稱 S / A / F 與 Gate 依 decision 011 §7 判定，不放寬。
