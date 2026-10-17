# Claude Code 工作規則：Inspection Robot + Active Perception

你目前只負責 **inspection-robot-active-perception**。不得修改其他 Project。

## 狀態

**Core 結案（decision 014，2026-10-13）：v1（decision 010）＋ v2（decision 011–013）。Advanced B 完成（decision 019）。作品集整理完成（2026-10-14）。v5 完成（decision 035，2026-10-16）。E0（decision 036）與 D3×P0 / H-P（decision 037）結案、研究成果與工程功能整理（2026-10-17）。**

**本專案暫時正式結案（使用者 2026-10-17）**：不再自行擴張研究，不開新的研究方向或實驗；Future Work 保留，等使用者決定是否重新啟動。只做使用者明確要求的維護。

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
- README 有英文（`README.md`，國際求職入口）與繁體中文（`README.zh-TW.md`，完整紀錄）兩版；主要數字都由 `tests/test_readme_claims.py` 對照已 commit 的結果，改 README 時不得與結果檔不一致。CI：`.github/workflows/ci.yml`（不需 Docker / GPU）。
- **R0 真實環境適應研究完成**（decision 020–023）：R0a 真實照片（Open Images；A1 通過、A2 未通過）、R0b 模擬的 depth / 位姿誤差（R1 / R2 通過，但 absent 判不出）。
  三種驗證（真實照片 / 模擬雜訊 / 實機）不得混為一談；`r0b` 與 R0a 正式集都已用過。實機仍未做。
  B 的資料只用 `nav-*` namespace（`Split.NAV_DEV`）；GT 位姿 / 標籤只用於評分，判定只用 AMCL 估計位姿 + 機載影像 + detector。

- **v3 完成**（decision 024–026）：
  - 正式資料 `v3` / `v3-dx` 已用過；V1–V3、V5 通過，V4（D2×L2）未通過。
  - 凍結設定 `activeperception/v3/frozen_v3.py`；開發資料是 `v3-dev`、`v3-dev-dx`。
- **A detector-v2 完成**（decision 027 → 030）：T1 未通過（偏難負樣本誤報 8.4% → 4.7%），T2–T4 通過。
  - `detector-v2` 不取代凍結的 `detector-v1`；test 與 `detv2-sim` 已用過、封存。
- **v4 與 D3 正式驗證完成**（decision 029 / 031 / 032）：W1–W6、D1 全部通過；凍結設定 `activeperception/v4/frozen_v4.py`。
  - `v4` / `v4-dx` 已用過、封存；v3 在 D2×L2 再次失敗 1 次，v4 擋下；v4 的代價是 absent 較難判。
- **B depth 模型檢查**（decision 028）：真實 D435 / D455 平面資料的量測完成；D3 的正式驗證在 decision 032 完成（v3 與 v4 在 D3 下都安全）。
- **v5 完成並正式結案**（decision 033 → 034 → 035；使用者 2026-10-16 確認，不修改、不重跑）：v5 = 凍結 v4 ＋ see-v5（缺值位姿被看穿位姿左右包住時不否決，k = 14），凍結設定 `activeperception/v5/frozen_v5.py`。
  - 正式（`v5` / `v5-dx`，只跑一次）：X1–X4 全部通過；Rule budget 3 D2×L2 +0.237、D3×L1 +0.138；absent@5 D3×L1 0.637 → 0.950。`v5` / `v5-dx` 已用過、封存。
  - 比例自我校正（decision 033 原主題）在開發中排除；不包住的版本只報告（也安全）。
- **zone 內相似物件**（decision 036）：E0 完成並封存，**E1 暫緩**；不得把單張影像的變換當作多視角證據；v1 / v2 比較必須同條件。
- **Future Work（都未啟動，使用者 2026-10-17：不得自行開啟新的正式研究方向）**：E1、D3×P0 的定位不確定性、立體遮蔽帶測試、rule-nbv-v2 的增益預測、實機量測（見 `NEXT.md`、README「後續與 Future Work」）。
- **D3×P0**（decision 037，**結案** 2026-10-17）：診斷完成（`docs/d3p0-diagnosis.md`）——失敗來自矛盾規則浪費選中的視角，不是不可觀測。H-P 開發評估（`docs/hp-development.md`）決策安全全 0、absent 大幅改善，但逐視角安全代理 S2 不成立 → 使用者決定結束研究線：**H-P 記為未通過安全 Gate 的研究假設**，不凍結、不做正式實驗、不調整門檻；`activeperception/v6/` 的 `hp_c` 預設 0，任何正式管線都不使用。v5 維持正式版本。D3×P0 的定位不確定性列入 Future Work（未啟動）。不得以提高 absent 判定率為由增加 false absent。
- **資源**：任何重工作前先跑 `uv run python -m activeperception.preflight`（鎖、CPU、RAM；Apple GPU 加 `--gpu`）；鎖存在或負載過高就不啟動。Mac 上可能有不取鎖的工作。text-6 事件紀錄：`docs/incidents/`，交由 Rust HNSW 專案處理，本專案不跨專案操作。

目前沒有進行中的實驗；需要使用者決定的下一步見 `NEXT.md`。GitHub remote：`origin`，**Public**（使用者 2026-10-17 核准），https://github.com/jingwenliu0113-afk/inspection-robot-active-perception。
**授權：BSD-3-Clause**（原創程式碼，`LICENSE`）；第三方內容保留原授權（`THIRD_PARTY_NOTICES.md`）。不得加入 AGPL / GPL 依賴（`tests/test_detector.py` 檢查 ultralytics）。
本 repo 的 commit email 已設為 GitHub noreply（repo-local git config）；不得改寫 Git 歷史。每個 milestone commit 後 push。

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
