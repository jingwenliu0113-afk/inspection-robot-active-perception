# Holdout：v1 vs v2（decision 011 / 012 / 013）

- 指令：`python -m activeperception.experiment_v2 holdout --episodes data/episodes/gazebo-holdout.json --detections runs/holdout/detector-v1.jsonl --renders renders/holdout --out results/holdout`（只跑一次）
- commit `e450414`（工作目錄乾淨）；`holdout` split 150 scene groups / 600 episodes，decision 011 之後產生、未參與開發
- `report.json`：v1、v2 兩組設定各自的 summary（budget 1–8，正式 budget 有 CI）、成對差異、GT 分層、校準、殘餘失敗、Gate；
  消融（decision-v2 + rule-nbv-v1）；預先登錄的宣稱 S / A / F；detector 面積 / confidence vs 偵測
- `outcomes.jsonl`：每個 (config, method, budget, seed, episode) 的評分
- `detector-v1.jsonl`：本次使用的偵測快取（RTX 5070 Ti、GPU lock）

判定見 [decision 013](../../docs/decisions/013-holdout-v1-v2-result.md)。v1 原 test 結果在 `results/test-v1/`，未更動。
