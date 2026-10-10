# Claude Code 工作規則：Inspection Robot + Active Perception

你目前只負責 **inspection-robot-active-perception**。不得修改其他 Project。

## 狀態

**Active（2026-10-10 啟動）。目前在 Core，尚無正式結果。**

已完成：frozen task definition（decision 002–004）、seeded episode generator、teleport harness、
shared decision rule、Single / Random / Rule / Oracle 四個 policy、grader、metrics（cluster bootstrap CI）、
69 個 correctness tests、synthetic world（僅供開發與測試）。

尚未完成：Gazebo Harmonic 環境與 world、detector 整合、pilot、budget / rule 參數凍結、正式 test。

## 每個 session 的第一步

1. 讀 `SPEC.md`、`NEXT.md`、`MACHINE_POLICY.md`、`docs/EXPERIMENT_RULES.md`、`docs/decisions/`。
2. `git status`，確認仍在 Core。
3. `uv sync && uv run pytest` 必須全綠才能往下。
4. 任何會改變實驗定義的決策先寫 decision log，再改程式。
5. Gate 未明確通過前不得進 Advanced；Optional 只有使用者明確要求才做。

## 工作循環

每個 milestone：tests → decision log（若影響實驗定義）→ commit → 更新 `NEXT.md` → 下一項。
一般 milestone 完成不需要停下來問使用者。只有以下情況才停：

- 需要 sudo、credential、付費服務、大型下載（> 1 GB）。
- 需要使用者做研究設計決策（例如 detector 選型、budget 最終值）。
- 所有可做的 Core 工作都 blocked。

## 專案邊界

- Core 的研究問題是 **active perception 是否能在固定 viewpoint budget 下減少 inconclusive inspection**，不是做完整自主機器人產品。
- Core 用 teleport / deterministic viewpoint placement 隔離 perception 與 viewpoint selection，不引入 Nav2。
- Core 不做 RL。
- candidate viewpoints 不得使用 object ground-truth pose、visibility label 或其他部署時拿不到的資訊。
- simulator ground truth 只能用於離線評分與 oracle upper bound，不得當作 deployable policy 的輸入。
- 四個方法共用同一條 decision rule（`activeperception/decision.py`）；方法之間只能差在 viewpoint 選擇。
- **synthetic world 的數字不是研究結果**，不得寫進 README 結果區或用於 Gate 判斷；正式結果只來自 Gazebo Harmonic。

## 共通執行邊界

- 不得自行擴張成 SLAM、multi-robot、通用 robotics framework。
- 不得看到結果後修改 success definition、viewpoint budget、split 或 metric；要改只能以新版本號在新一輪 test 報告並保留舊結果。
- 每次 session 結束前更新 `NEXT.md`。
- 發現 SPEC 與實作不一致時先記錄差異（decision log 或 NEXT.md），不要默默改規格。
- detector training / heavy GPU inference 必須遵守 `MACHINE_POLICY.md` 的共享 `/tmp/ai-portfolio-gpu.lock`；拿不到鎖就改做其他 Core，不得搶資源。
- Mac 上的 Gazebo 容器不得干擾其他 Project 的 Docker container / network / volume；不做全域 Docker prune / restart。
