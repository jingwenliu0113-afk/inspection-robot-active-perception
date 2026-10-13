# Failure analysis（Core 結案，decision 014）

本文件**只讀已 commit 的正式結果**，沒有在 `core` test 或 `holdout` 上重跑任何方法，也**不回饋到任何凍結參數**（decision 014）。
四組資料**分開報告，不合併**：

| 名稱 | 來源 | 設定 | 用途 |
|---|---|---|---|
| `test/v1` | `results/test-v1/` | decision-v1 + rule-nbv-v1 + oracle-v1 | v1 正式 test（decision 010） |
| `holdout/v1` | `results/holdout/` | 同上（原封不動的 v1） | v1 結論的獨立重現（decision 013） |
| `holdout/v2` | `results/holdout/` | decision-v2 + rule-nbv-v2 + oracle-v2 | v2 正式評估（decision 013） |
| `holdout/ablation` | `results/holdout/` | decision-v2 + rule-nbv-v1（只有 Rule） | 區分改善來源 |

§5 的平手分析例外：它用**開發資料**（core train / val）重跑凍結的 v2 策略，程式拒絕 test 與 holdout。

重現：

```bash
uv run python -m activeperception.failure_analysis --out results/failure-analysis \
    --dev-episodes data/episodes/gazebo-core.json --dev-detections results/core/detector-v1.jsonl --dev-renders renders/core
```

完整數字：[`results/failure-analysis/summary.json`](../results/failure-analysis/summary.json)。

## 1. 錯誤型態：Rule 從不給出錯誤的肯定答案

| | Rule 錯誤的肯定答案 | false present（全部方法） | false absent |
|---|---|---|---|
| `test/v1` | 0 | 0 | Random 1 個 episode：`core-g0103-v0`（seeds 3、4，budget ≥ 2） |
| `holdout/v1` | 0 | 0 | Random 1 個 episode：`holdout-g0046-v2`（seed 3，budget ≥ 2） |
| `holdout/v2` | 0 | 0 | **無**（所有方法、所有 budget） |
| `holdout/ablation` | 0 | — | 無 |

兩個 false absent 都是 `unobservable`（物件存在、初始視角被擋）：Random 挑到兩個「zone 大致看得到、但消防栓剛好被擋」的視角，decision-v1 的扇區條件因此成立。
v1 在原 test 上出現的這種失敗在 holdout **同樣出現**；decision-v2 要求看穿每個候選位置，結構上排除了它。

**Rule 的每一個失敗都是 `inconclusive`**，沒有任何一個是錯誤的 `present` / `absent`。

## 2. Rule 失敗歸因：budget 限制，還是視角選擇？

把每個 Rule 失敗依「同一條判定規則、同一個 budget 下，Oracle 是否答對」分成兩類：

- **結構性（Oracle 也失敗）**：在這個 budget 與這條判定規則下，12 個候選中怎麼選都答不出來（budget 2 只有一次選擇，因此這是窮舉的結論）。
- **視角選擇（Oracle 答對）**：同樣的候選，更好的選擇就能答對——這是 Gate 4「Rule 與 Oracle 差距」的組成。

![Rule 失敗歸因](figures/failure_attribution.png)

| 資料 | budget 2：失敗 = 結構性 + 視角選擇 | budget 3：失敗 = 結構性 + 視角選擇 |
|---|---|---|
| `test/v1`（524） | 154 = 152 + 2 | 2 = 0 + 2 |
| `holdout/v1`（600） | 190 = 173 + 17 | 19 = 0 + 19 |
| `holdout/ablation`（600） | 38 = 0 + 38 | 4 = 0 + 4 |
| `holdout/v2`（600） | **26 = 0 + 26** | **1 = 0 + 1** |

- v1 在 budget 2 的失敗約 90% 是結構性的，而且全部是 `absent`：decision-v1 需要 2 個有效扇區，初始視角被擋時 budget 2 只剩一個視角，Oracle 也湊不到。
- decision-v2 只要求「每個候選位置都被某個視角看穿」，一個好的視角就夠 → **結構性失敗全部消失**。這就是 v2 改善的主要來源（§3）。
- 換成 decision-v2 之後，剩下的失敗**全部可歸因於視角選擇**（Oracle-v2 每一件都答對）——這正是 v2 在 budget 2 的 Gate 4 未通過（Oracle − Rule = 0.043）。

## 3. 改善來源：成對轉移（holdout，同一批 600 episodes）

| 轉移 | 只改了什麼 | budget 2：修好 / 弄壞 | budget 3：修好 / 弄壞 |
|---|---|---|---|
| v1 Rule → 消融 | **判定規則**（decision-v1 → v2） | **152 / 0** | 15 / 0 |
| 消融 → v2 Rule | **視角策略**（rule-nbv-v1 → v2） | 31 / 19 | 4 / 1 |
| v1 Rule → v2 Rule | 兩者 | 171 / 7 | 19 / 1 |

- **判定規則的改變是單調的**：沒有任何一個 v1 答對的 episode 因此變錯。
- **策略的改變有得有失**：budget 2 修好 31 件、弄壞 19 件，淨 +12（+0.020 [−0.020, 0.058]，不顯著）。
- 結論（decision 014 的正式說法）：**v2 的改善主要來自 absent 判定規則，不是 NBV 策略。**

### v2 相對 v1 的退步（v1 答對、v2 沒答對）

- budget 2 共 7 件，全部是 `unobservable → inconclusive`：`holdout-g0019-v2`、`g0058-v0`、`g0088-v2`、`g0105-v2`、`g0113-v0`、`g0113-v2`、`g0133-v0`。
  v1 策略（以及消融）在第二個視角就看到消防栓；rule-nbv-v2 選了另一個視角，只看到一部分或完全看不到（兩件有 0.35–0.40 的弱偵測，低於 τ_present 0.7）。
- budget 3 共 1 件：`holdout-g0058-v1`（`absent → inconclusive`，三個視角後看穿 84%）。
- 沒有任何一件退步成錯誤的肯定答案。

## 4. 為什麼 rule-nbv-v2 沒有顯著貢獻：分數平手時按編號選（開發資料）

在 core train / val（開發資料）上，對凍結的 v2 在 budget 2 的「第二個視角」決策點計算每個候選的分數：

| split | 初始視角 zone 被擋（可見 < 0.3） | 決策點 | 最高分有平手 | 平均平手候選數（共 12） |
|---|---|---|---|---|
| train | 是 | 285 | **230（81%）** | 8.0 |
| train | 否 | 10 | 2 | 1.2 |
| val | 是 | 96 | **72（75%）** | 7.6 |
| val | 否 | 11 | 5 | 1.5 |

機制：

1. 初始視角被柱子擋住時，已知地圖幾乎沒有「已知空」的格子。
2. 對每個沒被已知障礙擋住的候選，所有未看穿位置的視線都會經過未知格子，因此 `clear_gain` 都等於 `p_unknown`（0.5）→ **平手**。
3. 凍結的 `w_novelty`、`w_attraction`、`w_visibility` 都是 0（decision 012 的平手規則偏好「非零權重最少」），沒有其他特徵打破平手，
   `sorted(scored)[0]` 因此選**編號最小**的候選。
4. 候選編號從每個 scene group 的隨機相位開始，所以實際行為接近「排除已知被擋的候選後，按固定順序挑一個」——比 Random 好（會避開已知障礙），但沒有利用更多資訊。

holdout 的描述性觀察與此一致：v2 在 budget 2 的 26 個失敗，第二個視角**全部**是候選 0 或 1（`report.json` 的 `viewpoint_sequence`）。

**這是凍結 v2 的已知限制，本 Core 不修正。** 修正（例如平手時改用 novelty、或對未知空間用更有資訊的先驗）屬於 v3：
需要新的 decision log，並在**新的、未參與開發的資料**上驗證；原 test 與 holdout 都不能再用（decision 014）。

## 5. 失敗與場景特徵

**初始視角是否看得到 zone** 是最強的分界：四組資料中，初始視角 zone 可見 ≥ 0.3 的 episodes **沒有任何 Rule 失敗**；所有失敗都發生在初始視角被擋的 episodes。

柱子數量（budget 2，Rule 失敗率）：

| 柱子數 | `test/v1` | `holdout/v1` | `holdout/v2` |
|---|---|---|---|
| 1 | 27.0%（53 / 196） | 30.4%（51 / 168） | 2.4%（4 / 168） |
| 2 | 32.1%（54 / 168） | 30.0%（60 / 200） | 1.5%（3 / 200） |
| 3 | 29.4%（47 / 160） | 34.1%（79 / 232） | **8.2%（19 / 232）** |

v1 的失敗率幾乎不隨柱子數變化（被結構性失敗主導）；v2 的殘餘失敗集中在 3 根柱子的場景（19 / 26）——柱子越多，平手時的固定順序越容易挑到只能部分看穿的視角。

## 6. v1 結論在 holdout 的重現

| v1 結論（decision 010，原 test） | holdout | 判定 |
|---|---|---|
| Rule 穩定勝過 Random / Single | rule − random +0.075 / +0.070（CI 下界 > 0） | **重現** |
| Rule 接近 Oracle（差 0.004） | 差 0.028 [0.012, 0.048] / 0.032 [0.012, 0.055] | **未重現** |
| Random 偶發 false absent | 同樣 1 個 episode | 重現 |
| 殘餘失敗以 budget 結構限制為主 | budget 2：173 / 190 是結構性 | 重現 |

holdout 上 v1 的 budget 3 差距來自 19 件視角選擇失敗（17 absent、2 unobservable）；原 test 只有 2 件。decision 010 原文不改，原 test 的 0.004 視為偏樂觀的單次估計。

## 7. 本分析不做的事

- 不改任何凍結參數、判準、split 或 metric；不在 test / holdout 上重跑任何方法。
- §4 的平手現象只記錄為限制，不據此調整 v2。
- 任何由本分析得到的改進想法，都必須先寫 decision log，並在新的 namespace 產生的新資料上驗證。
