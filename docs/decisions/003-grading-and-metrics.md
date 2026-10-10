# 003 — Grading 與 metrics 定義

- **日期**：2026-10-10
- **狀態**：凍結
- **是否在看過正式結果後才新增 / 修改**：否。

## 問題

SPEC §7 列出要報的指標，但 `inconclusive` 沒有天然的 GT 類別，必須先定義「什麼算對」，否則 grader 可能把 `inconclusive` 偷偷當成錯誤或當成 absent。

## 定義（`activeperception/grader.py`）

每個 episode 的 expected label（與 budget 無關）：

| GT state | revealable | expected |
|---|---|---|
| visible | — | `present` |
| unobservable | yes | `present` |
| unobservable | no | `inconclusive` |
| absent | — | `absent` |

每個 outcome 記錄：

- `correct` = decision == expected
- `false_absent` = 物件存在且 decision == `absent`（最危險的錯誤）
- `false_present` = 物件不存在且 decision == `present`
- `inconclusive` = decision == `inconclusive`
- `viewpoints_used`

`inconclusive` 永遠不是 false_absent 也不是 false_present；它只在 expected 也是 `inconclusive` 時算 correct。這讓「誠實說不知道」有代價（不算成功）但不被當成危險錯誤。`tests/test_grader.py` 以 12 列真值表驗證。

## Metrics（`activeperception/metrics.py`）

| 指標 | 定義 |
|---|---|
| accuracy | mean(correct) |
| macro_f1 | 對 expected ∪ predicted 中出現過的類別取 F1 平均；分母為 0 的 F1 記 0。只預測從不該出現的類別會被扣分，但資料裡沒有、方法也沒預測的類別不會把平均拉低 |
| false_absent_rate | 分母 = 物件存在的 episodes |
| false_present_rate | 分母 = absent episodes |
| inconclusive_rate | 分母 = 全部 |
| avg_viewpoints | 平均觀測數（含初始） |
| ece | 只對 definitive decision（present / absent）用其宣告的 confidence 做 10-bin ECE；另輸出 reliability bins |
| by_state | 以上指標依 visible / unobservable / absent 分層 |
| success vs budget | 以 `sweep` 在多個 budget 重跑取得 |

## 信賴區間

cluster bootstrap：以 scene group 為 cluster，有放回重抽 group，1000 次，percentile 95% CI，seeded。

## 候選方案

- 曾考慮把 `inconclusive` 一律視為錯誤：否決，會讓 false-absent 與 inconclusive 混在一起，違反 SPEC「不把看不到當不存在」。
- 曾考慮 expected label 依 budget 決定（budget 內 oracle 可揭露才算 present）：否決，GT 不應隨方法參數變動；budget 的影響由 success-vs-budget 曲線呈現。

## 被凍結的項目

expected label 對照表、四種 outcome 旗標、各指標分母、macro-F1 類別集合規則、ECE 只算 definitive decision、cluster bootstrap 設定。
