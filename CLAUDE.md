# Claude Code 工作規則：Inspection Robot + Active Perception

你目前只負責 **inspection-robot-active-perception**。

## 狀態

這是 **Future / Parked Project**。除非使用者明確說要開始這個專案，否則不要自行安裝 ROS、Gazebo、下載模型、建立模擬世界或實作功能。

## 正式開始後的第一步

1. 完整閱讀 `SPEC.md`。
2. 閱讀 `NEXT.md`。
3. 閱讀 `MACHINE_POLICY.md`。
4. 閱讀 `docs/EXPERIMENT_RULES.md`。
5. 檢查 `git status`。
6. 確認仍在 Core。
7. 任何會改變實驗定義的決策先寫 decision log。
8. Gate 未明確通過前不得進 Advanced。
9. Optional 只有使用者明確要求才做。

## 專案邊界

- Core 的研究問題是 **active perception 是否能在固定 viewpoint budget 下減少 inconclusive inspection**，不是做完整自主機器人產品。
- Core 先用 teleport / deterministic viewpoint placement 隔離 perception 與 viewpoint selection，不先引入 Nav2。
- Core 不做 RL。
- candidate viewpoints 不得使用 object ground-truth pose、visibility label 或其他部署時拿不到的資訊。
- 不能把 simulator ground truth 當作 agent/policy 的輸入，只能用於離線評分與 oracle upper bound。

## 共通執行邊界

- 不得自行擴張成 SLAM、multi-robot、通用 robotics framework。
- 不得看到結果後修改 success definition、viewpoint budget、split 或 metric。
- 每次 session 結束前更新 `NEXT.md`。
- 發現 SPEC 與實作不一致時先記錄差異，不要默默改規格。
- 正式啟動後，detector training / heavy GPU inference 必須遵守 `MACHINE_POLICY.md` 的共享 `/tmp/ai-portfolio-gpu.lock`；拿不到鎖就改做其他 Core，不得搶資源。
