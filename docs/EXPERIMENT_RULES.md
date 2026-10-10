# Inspection Robot + Active Perception 實驗規範

## Core 原則

- scene split 先凍結再看 test。
- candidate viewpoints 對所有方法一致。
- deployable policy 不得讀 simulator ground truth。
- `present / absent / inconclusive` 三類分開評分。
- 不把 no-detection 直接當 absent。
- teleport Core 與 Nav2 Advanced 結果分開。

## 統計

- episode / scene group 為 cluster。
- 報 confidence interval 或 bootstrap。
- visible / unobservable / absent 必須分層報告。
- 同時報 accuracy 與 false-absent，避免只看總分。

## Gate

Advanced 不是自動下一步。

只有 Core 留下明確、可重現問題才進 Advanced。

RL 只有 rule-based 與 oracle 存在值得解釋的 gap 時才允許。
