# Claude Code 工作規則：Inspection Robot + Active Perception

你目前只負責 **inspection-robot-active-perception**。不得修改其他 Project。

## 狀態

**Core 結案（decision 014，2026-10-13）：v1（decision 010）＋ v2（decision 011–013）。**

- v1：正式 test 一次；Rule 穩定勝過 Single / Random。holdout 上「接近 Oracle」未重現（decision 013）。
- v2：看過 v1 test 後提出；只用 core train / val 開發，在新的 `holdout` split 一次性與 v1 分開比較；
  所有方法 false-absent = 0，Rule budget 2 0.683 → 0.957。**改善主要來自 absent 判定規則（`decision-v2`），不是 NBV 策略**（不得描述成策略改善）。
- Gate 未通過：v1 Gate 4（holdout）、v2 Gate 4（budget 2）。見 decision 014 §2。
- **原 `core` test 與 `holdout` 都已封存**（`activeperception/seal.py`、`SEALED.sha256`、`tests/test_seal.py`）：不得用於任何新版本的開發、調參或正式驗證，不得合併；
  不得根據 holdout 結果調整模型或規則。新版本需要新 namespace、未參與開發的資料。
- v1 / v2 的程式、結果、失敗紀錄都保留（`frozen.py` / `frozen_v2.py`、`results/test-v1/`、`results/holdout/`、`docs/failure-analysis.md`）。
- **Advanced C（RL）**：使用者決定暫不進行。**Advanced B（Nav2）**：只完成評估（`docs/advanced-b-nav2-evaluation.md`），未經使用者決定不得啟動。

下一步需要使用者決定，見 `NEXT.md`。GitHub remote：`origin`（private，不加 LICENSE）。每個 milestone commit 後 push。

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
