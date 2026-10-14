# Claude Code 工作規則：Inspection Robot + Active Perception

你目前只負責 **inspection-robot-active-perception**。不得修改其他 Project。

## 狀態

**Core 結案（decision 014，2026-10-13）：v1（decision 010）＋ v2（decision 011–013）。Advanced B 完成（decision 019）。作品集整理完成（2026-10-14）。**

- v1：正式 test 一次；Rule 穩定勝過 Single / Random。holdout 上「接近 Oracle」未重現（decision 013）。
- v2：看過 v1 test 後提出；只用 core train / val 開發，在新的 `holdout` split 一次性與 v1 分開比較；
  所有方法 false-absent = 0，Rule budget 2 0.683 → 0.957。**改善主要來自 absent 判定規則（`decision-v2`），不是 NBV 策略**（不得描述成策略改善）。
- Gate 未通過：v1 Gate 4（holdout）、v2 Gate 4（budget 2）。見 decision 014 §2。
- **原 `core` test 與 `holdout` 都已封存**（`activeperception/seal.py`、`SEALED.sha256`、`tests/test_seal.py`）：不得用於任何新版本的開發、調參或正式驗證，不得合併；
  不得根據 holdout 結果調整模型或規則。新版本需要新 namespace、未參與開發的資料。
- v1 / v2 的程式、結果、失敗紀錄都保留（`frozen.py` / `frozen_v2.py`、`results/test-v1/`、`results/holdout/`、`docs/failure-analysis.md`）。
- **Advanced C（RL）**：使用者決定暫不進行。
- **Advanced B（Nav2）完成**（decision 015–019）：B0 → decision 016（位姿精修 + 看穿餘裕 + 停點重定位）→ B1 → B2 正式評估 `nav-b2`
  Q1–Q4 全部成立。`nav-b2` 已用過，不得再用於開發。
- **使用者決定（2026-10-14）**：暫不購買實體機器人、不進 Advanced C。後續建議見 `docs/roadmap-real-inspection.md`（未啟動，需使用者決定）。
- README 的主要數字由 `tests/test_readme_claims.py` 對照已 commit 的結果；改 README 時不得與結果檔不一致。
- **R0 真實環境適應研究完成**（decision 020–023）：R0a 真實照片（Open Images；A1 通過、A2 未通過）、R0b 模擬的 depth / 位姿誤差（R1 / R2 通過，但 absent 判不出）。
  三種驗證（真實照片 / 模擬雜訊 / 實機）不得混為一談；`r0b` 與 R0a 正式集都已用過。實機仍未做。
  B 的資料只用 `nav-*` namespace（`Split.NAV_DEV`）；GT 位姿 / 標籤只用於評分，判定只用 AMCL 估計位姿 + 機載影像 + detector。

- **v3 完成**（decision 024–026）：
  - 正式資料 `v3` / `v3-dx` 已用過；V1–V3、V5 通過，V4（D2×L2）未通過。
  - 凍結設定 `activeperception/v3/frozen_v3.py`；開發資料是 `v3-dev`、`v3-dev-dx`。
- **A detector-v2**（decision 027，使用者 2026-10-15 授權，只限此協定可重新訓練 detector）：
  - 協定、資料、程式完成；訓練需 RTX 5070 Ti（`tools/detv2_gpu.sh`，GPU lock）。
  - test（`data/detv2/test.csv`、`detv2-sim`）在正式評測前不得執行任何 detector。
- **B depth 模型檢查**（decision 028）：真實 D435 / D455 平面資料的量測完成；D3 只做開發檢查，正式結論需新 decision 與新資料。

RTX 恢復後的步驟、以及其餘需要使用者決定的事，見 `NEXT.md`。GitHub remote：`origin`（private，不加 LICENSE）。每個 milestone commit 後 push。

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
