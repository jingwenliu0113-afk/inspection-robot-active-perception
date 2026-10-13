# 018 — Advanced B2：Nav2 正式評估協定（預先登錄）

- **日期**：2026-10-14
- **狀態**：凍結；寫於 `nav-b2` 產生之前。結果以 decision 019 報告，只跑一次。
- **是否在看過正式結果後才新增 / 修改**：否。B1（`nav-b1`）是整合用的開發資料，只用來確認管線，沒有調整任何凍結值。

## 1. 凍結的設定

decision 017 §2 全部（`decision-v2`、`rule-nbv-v2`、`oracle-v2`、`detector-v1`、`gen-nav-v1`、TurtleBot 4 桅桿相機、Nav2 整合設定、
`nav-pose-v1`、`nav-margin-v1`、`nav-relocalize-v1`）；Random seeds 0–2；budget 5 一次執行給出 budget 1–5。

## 2. 資料

新 namespace `nav-b2`（新 split `nav-eval`），**40 scene groups × 4 variants = 160 episodes**，本檔 commit 之後才產生；
樣本數依 B1 的執行時間決定（每個工作含容器啟動約 55 s；960 個工作、4 個並行約 4 小時），不是依任何結果決定。
teleport 對照 render、GT、teleport 偵測、Nav2 閉迴路各跑一次。

## 3. 預先登錄的問題與判定（正式 budgets 2、3；1、5 只報告）

統計：scene-group cluster bootstrap（1000 次，seed 同 Core），成對差異在同一組重抽上計算。

| # | 問題 | 判定 |
|---|---|---|
| Q1 安全 | Nav2 下所有方法、所有 budget 的 false absent 與 geometric risk | 皆 0 → **成立**；否則列出每一件 |
| Q2 導航造成的準確率變化 | 每個方法 Nav2 − teleport 的 accuracy 成對差異 | CI 下界 > −0.05 →「不劣於 teleport」；否則如實報告損失 |
| Q3 主動視角在 Nav2 下是否仍有用 | Nav2 下 Rule − Single、Rule − Random 的 accuracy | CI 下界 > 0 →「成立」；否則「未成立」 |
| Q4 成本 | 每個 episode 的行走距離與導航時間：Rule vs Random（成對） | 報告差異與 CI |

SPEC Advanced B 指標一併報告：path success、reachable viewpoint rate（Nav2 成功且真實到點 ≤ 0.10 m / 0.10 rad）、
collision、timeout、navigation latency；以及 GT 狀態分層、重定位次數、精修失敗。

## 4. 不做的事

- 不依 `nav-b2` 結果調整任何參數；任何改進都是新版本、新資料。
- 結果與 Core（teleport、gen-v2 場景）分開報告，不合併；場景（圍牆、固定環半徑與高度）不同，Core 的數字不能直接比較。

## 5. 執行與實作

- 方法與 seeds：Single、Rule-NBV v2、Oracle v2（seed 0），Random seeds 0–2；每個（episode、方法、seed）一個容器，budget 5（`docker/nav_b1.sh 4 nav-b2`，動態佇列、可續跑、失敗重試一次，重試照實報告）。
- 分析：`python -m activeperception.nav.b1_analysis --ns nav-b2`（`claims`：Random 先在 seeds 上平均成每個 episode 一個值；
  scene-group cluster bootstrap 1000 次、seed 0；正式 budgets 2、3；不劣性邊界 0.05）。
- 結果寫入 `results/nav-b2/` 並加入 `SEALED.sha256`；`nav-b2` 之後不再用於任何開發。
