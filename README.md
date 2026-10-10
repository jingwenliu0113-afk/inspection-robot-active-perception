# Inspection Robot + Active Perception

> **狀態（2026-10-10）：Core 進行中，尚無正式結果。**
> 目前完成：frozen task definition、seeded episode generator、teleport harness、
> shared decision rule、4 個 baseline policies、grader、metrics（cluster bootstrap CI）與 correctness tests。
> 尚未完成：Gazebo Harmonic world、detector 整合、pilot、正式 test。
> 下面任何數字都來自 **synthetic world**，只用於驗證 pipeline 正確性，**不是研究結果**。

## 一句話問題

在物件可能「可見、被遮擋、根本不存在」的 inspection task 中，active perception 能不能在固定觀測預算下，
比單一視角與隨機移動更可靠地判斷 `present / absent / inconclusive`？

完整研究定義見 [SPEC.md](SPEC.md)，實驗規範見 [docs/EXPERIMENT_RULES.md](docs/EXPERIMENT_RULES.md)，
所有會影響結論的設計決策見 [docs/decisions/](docs/decisions/)。

## 任務定義（已凍結，見 decision 002 / 003 / 004）

| Ground truth（每個 episode） | 系統輸出 |
|---|---|
| `visible`：物件存在且初始視角可觀測 | `present` |
| `unobservable`：物件存在但初始視角被遮擋 | `absent` |
| `absent`：物件不存在 | `inconclusive` |

- Core 以 **teleport** 到候選 viewpoint，不含 Nav2，不含 RL。
- 候選 viewpoint 只由 inspection zone 與 scene-group seed 決定，與物件位置 / 遮擋無關（有 leakage test）。
- 四個方法共用同一條 decision rule，差別只在「選了哪些 viewpoint」。
- 「沒偵測到」不等於 `absent`；`absent` 需要足夠的 azimuth coverage 且視線未被擋。

## 方法

| Policy | 可用資訊 | 角色 |
|---|---|---|
| Single View | 初始視角 | baseline |
| Random NBV | 候選集合、seed | baseline |
| Rule-based NBV | detector confidence / bbox area / 觀測歷史 / viewpoint 幾何 / 深度推得的 zone 遮擋 | 受測方法 |
| Oracle NBV | simulator ground truth | upper bound，不可部署 |

## 快速開始

```bash
uv sync
uv run pytest
uv run python -m activeperception build-episodes --world synthetic --namespace dev --groups 60
uv run python -m activeperception sweep --episodes data/episodes/synthetic-dev.json --split val --budgets 1,3,5 --n-boot 200
```

## 目錄

```
activeperception/   核心套件（types / episodes / sim / decision / policies / harness / grader / metrics / cli）
tests/              correctness tests（determinism、leakage、budget、grader、metrics）
docs/decisions/     decision logs
data/episodes/      frozen episode sets（JSON）
```

## 環境

- 開發 / tests / 分析：Mac（Python 3.12，uv）。
- 正式模擬平台：ROS 2 Jazzy + Gazebo Harmonic（Ubuntu 24.04），環境方案見 decision 001 與 [MACHINE_POLICY.md](MACHINE_POLICY.md)。
