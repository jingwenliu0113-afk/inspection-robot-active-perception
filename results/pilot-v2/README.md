# Pilot 檢查（v2 設定，decision 011 / 012）— 不是研究結果

- 資料：`pilot` split（6 scene groups、24 episodes），與 v1 pilot 相同的 frames（`renders/pilot`、`renders/pilot-rerender`）。
- 設定：凍結的 `decision-v2` + `rule-nbv-v2`（+ Single / Random；oracle-v2 只在 replay 中，因為它要偷看未走訪的視角）。
- ROS 2 線上：`CONFIG=v2 OUT=runs/ros-v2 ./docker/ros_live.sh data/episodes/gazebo-pilot.json "single:1,single:3,random:3,random:5,rule:2,rule:3,rule:5" <24 個 episode id>`
- 檢查：`python -m activeperception.pilot ... --live runs/ros-v2 --config v2 --budgets 1,2,3,5 --out results/pilot-v2`

| 檢查 | 結果 |
|---|---|
| 1–5（三狀態、決定性、timestamp、transform、同候選集、grader） | 全部通過（frames 與 v1 pilot 相同） |
| 6. ROS 2 線上 = replay | 24 episodes × 7 個 (policy, budget)：viewpoint 序列 **168 / 168**、決策 **168 / 168** 相同；逐視角最高 confidence 差 ≤ 0.0037（Mac CPU vs CUDA） |

v1 的 pilot 結果在 `results/pilot/`，未更動。
