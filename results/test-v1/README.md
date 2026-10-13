# 正式 test v1（decision 009 / 010）

- 指令：`python -m activeperception.experiment test --episodes data/episodes/gazebo-core.json --detections runs/core/detector-v1.jsonl --renders renders/core --out results/test-v1`（只跑一次）
- commit `3dd52b9`（工作目錄乾淨）；`core` test split 131 scene groups / 524 episodes
- 版本：`gen-v2`、`label-v1`、`detector-v1`（FRCNN-MobileNetV3，`results/core/detector-v1.jsonl`）、`decision-v1`、`rule-nbv-v1`；Random NBV seeds 0–4
- `report.json`：所有指標（budget 1–8）、正式 budget {1, 2, 3, 5} 的 95% cluster bootstrap CI、成對差異、GT 狀態分層、
  reliability bins、detector 可見面積 / confidence vs 偵測成功、殘餘失敗清單、Gate 判定
- `outcomes.jsonl`：每個 (method, budget, seed, episode) 的評分結果

摘要與判定見 [decision 010](../../docs/decisions/010-core-test-result-and-gate.md) 與 README 結果區。
