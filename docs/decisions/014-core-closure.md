# 014 — Core 結案：Gate 總表、改善歸因、資料封存

- **日期**：2026-10-13
- **狀態**：**Core 結案（v1 + v2）**
- **是否在看過正式結果後才新增 / 修改**：是——本檔彙整 decision 010 與 013 已公開的結果、記錄使用者決定，並封存資料與結果。
  **沒有修改任何參數、判準、split、budget 或 metric**；decision 001–013 原文不改。

## 1. 使用者決定（2026-10-13）

1. **暫不進入 Advanced C（RL）**。
2. 先完成 Core 收尾：保留 v1 / v2 所有結果；明確記錄 Gate 未通過的項目；明確記錄 v2 的改善主要來自 absent 判定規則，而不是 NBV 策略。
3. 原 `core` test 與新 `holdout` **不得混用**；**不得根據 holdout 結果繼續調整模型或規則**。
4. 評估 Advanced B（Nav2）的可行性、範圍與環境需求，提出方案由使用者決定；**不自行啟動 Advanced B 或 C**。

## 2. Gate 總表（decision 009 §4 判準，原樣套用，不放寬）

| Gate 判準 | v1 @ core test（decision 010） | v1 @ holdout（decision 013） | v2 @ holdout（decision 013） |
|---|---|---|---|
| 1. Rule 穩定勝過 Random 與 Single（budget 2、3） | 通過 | 通過 | 通過 |
| 2. 非 candidate leakage | 通過 | 通過 | 通過 |
| 3. 明確、可重現的殘餘失敗 | 通過（156 件） | 通過（209 件） | 通過（27 件，全部 `inconclusive`） |
| 4. Rule 接近 Oracle（差 ≤ 0.02 或 CI 含 0） | 是（0.004） | **未通過**：budget 2 +0.028 [0.012, 0.048]、budget 3 +0.032 [0.012, 0.055] | **budget 2 未通過**：+0.043 [0.020, 0.070]；budget 3 通過（+0.0017） |

### 未通過 / 未成立的項目（明確列出）

1. **v1 的 Gate 4 在 holdout 未通過**：原 test 的「接近 Oracle」沒有重現。decision 010 原文不改，原 test 的 0.004 視為偏樂觀的單次估計。
2. **v2 的 Gate 4 在 budget 2 未通過**：Oracle 高 4.3 個百分點，差距全部可歸因於視角選擇（failure analysis §2）。
   依 SPEC，「Rule 已接近 Oracle → 停止，不需要 RL」這個停止條件**不成立**；Advanced C 在規範上**允許但不自動啟動**，使用者決定暫不進行。
3. **rule-nbv-v2 相對 rule-nbv-v1 沒有顯著改善**：消融 +0.020 [−0.020, 0.058]（budget 2）、+0.005 [−0.003, 0.020]（budget 3）。不宣稱新策略有改善。
4. **v2 有少量退步**：v1 答對、v2 沒答對的 episodes 在 budget 2 有 7 件、budget 3 有 1 件（全部變成 `inconclusive`，沒有錯誤答案）。

預先登錄的宣稱 S（安全）、A（Rule 準確率）、F（浪費視角）在 holdout 上**都成立**（decision 013）；F 的定義對 v2 有利，只作輔助。

## 3. 改善歸因（正式說法）

> **v2 的改善主要來自 absent 判定規則（`decision-v2`：以 depth 看穿每個候選位置作為 absent 的正面證據），不是 NBV 策略（`rule-nbv-v2`）。**

依據（全部來自已 commit 的結果；failure analysis §2–§4）：

- 消融：判定規則效果 +0.253 [0.215, 0.293]；策略效果 +0.020 [−0.020, 0.058]（budget 2）。
- 成對轉移：只換判定規則 → 修好 152、弄壞 0；只換策略 → 修好 31、弄壞 19。
- decision-v2 消除了 v1 全部的結構性失敗（budget 2：173 → 0）。
- 機制（開發資料 core train / val）：初始視角被擋時，75–81% 的第二視角決策是分數平手，由候選編號決定。

README、NEXT.md、CLAUDE.md 與任何對外說明都使用這個說法，不得把 v2 的改善描述成「選視角策略的改善」。

## 4. 資料封存

| 資料 | 已用於 | 狀態 |
|---|---|---|
| `core` train / val | v1、v2 開發 | 開發資料（可做 correctness 檢查，例如 v1 回歸測試、failure analysis §4） |
| `core` test | v1 正式 test 一次（commit `3dd52b9`） | **封存** |
| `holdout` | v1 / v2 / 消融正式比較一次（commit `e450414`） | **封存** |
| `pilot`、`detsel` | 管線檢查、detector 選型 | 不作正式評估 |

規則：

- `core` test 與 `holdout` 不再用於任何設計、調參、門檻選擇、模型選擇；兩者**不合併**，永遠分開報告。
- 對 holdout 的 failure analysis 只作描述，不產生任何參數變更；分析中看到的問題（例如平手）只能在 v3 處理。
- `core`、`holdout` 兩個 namespace 不再產生任何新版本的正式評估資料；新版本（含 Advanced B）需要在其 decision log 之後以**新 namespace** 產生資料。

程式強制：

- `tune.guard_split`：調參拒絕 `test` 與 `holdout`（既有）。
- `activeperception/seal.py`：正式 runner（`experiment test`、`experiment_v2 holdout`）偵測到封存的（episode set 內容 digest、split）時拒絕執行；
  只允許 `--reproduce`，而且輸出不得寫進 `results/`，只比對 `outcomes.jsonl` 是否逐位元相同。
- `SEALED.sha256`：釘住所有已 commit 的 `results/`、凍結的 episode sets、`frozen.py`、`frozen_v2.py`（40 個檔案）；
  `tests/test_seal.py` 在任何釘住的檔案改變時失敗。新增結果可以，改寫既有結果不行。

## 5. 最終凍結狀態

- v1：`activeperception/frozen.py`（decision 009）——不變。
- v2：`activeperception/frozen_v2.py`（decision 012）——不變。
- detector `detector-v1`（FRCNN-MobileNetV3）、world `gen-v2`、labeling `label-v1`、image `sha256:49d6e69b…`——不變。

## 6. 後續

- **Advanced C（RL）**：暫不進行（使用者決定）。若日後進行，需與同 budget 的 Random / Rule / Oracle 比較，且使用新資料。
- **Advanced A（detector fine-tuning）**：不成立（decision 010：瓶頸不是 perception）。
- **Advanced B（Nav2）**：可行性評估見 [`docs/advanced-b-nav2-evaluation.md`](../advanced-b-nav2-evaluation.md)，**待使用者決定**，不自行啟動。
