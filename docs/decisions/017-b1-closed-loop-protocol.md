# 017 — Advanced B1：閉迴路 Nav2 整合協定（預先登錄）

- **日期**：2026-10-14
- **狀態**：B1 協定凍結；寫於任何 B1 執行之前。B2 正式評估的宣稱另以 decision 018 預先登錄。
- **是否在看過正式結果後才新增 / 修改**：否——B 沒有正式結果；B0 / `nav-b0c` / `nav-b0d` 都是可行性資料。

## 1. 依據

B0 通過標準在 decision 016 附錄 C 的第二次確認（`nav-b0d`）全部成立（附錄 D）→ 依 decision 015 / 016 進 B1。

## 2. 凍結、B1 不調整的部分

- `decision-v2`、`rule-nbv-v2`、`oracle-v2`、`detector-v1`（Core 凍結值）。
- 場景 `gen-nav-v1` = `gen-nav-b0` 的設定（固定 2.0 m 環、1.1 m 桅桿相機、柱子間隙 0.35 m、8 m 圍牆）。
- 機器人與 Nav2 整合設定（到點容忍 0.07 m / 0.05 rad、AMCL 0.1 m / 0.1 rad）、`nav-pose-v1`、`nav-margin-v1`、`nav-relocalize-v1`。

## 3. B1 範圍（整合，不產生研究結論）

- 映像 `inspection-ap-navdet`（Nav2 映像 + Core 相同版本的 CPU torch），讓 detector 能在導航迴圈中執行。
- 閉迴路執行：每個（episode、方法、seed）一個全新容器；從初始視角出發 → decision 016 路徑判定 → 若 `inconclusive` 且未達 budget，
  由策略選下一個候選 → Nav2 導航 + 停點重定位 → 拍攝 → 判定，直到明確答案或 budget 5。
  各策略都不使用剩餘 budget，所以一次 budget 5 的執行同時給出 budget 1–5 的結果（前綴）。
- 方法：Single、Random（seeds 0–2）、Rule-NBV v2、Oracle v2（GT 與 teleport 觀測作上限，不可部署）。
- teleport 對照：同一批 episodes 在同一 Nav 場景（無機器人）以 Core 流程 render 13 個視角，replay 同樣四個方法——用來區分導航造成的差異。
- 新指標（SPEC Advanced B）：path success、reachable viewpoint rate、collision / timeout、navigation latency、行走距離、重定位次數；
  判定指標同 Core（accuracy、false absent / present、inconclusive、geometric risk），GT 狀態分層。
- 開發資料：新 namespace `nav-b1`（`Split.NAV_DEV`），4 scene groups × 4 variants（同 gen-v2：present / absent × 柱子微擾），只用於整合與除錯；不調整 §2 的任何凍結值。
- teleport 對照與 Nav2 使用同樣的 Random seeds 0–2（Core 為 0–4；Nav2 每次執行成本高，B 全程用 3 個 seeds，兩邊相同才能成對比較）。

## 4. B1 完成條件

- `nav-b1` 上全部方法跑完、teleport 對照 render 完成、報告產生、tests 綠燈。
- 之後寫 decision 018（B2 的宣稱、樣本數、統計方式），再在全新的 `nav-b2` 上只跑一次。
