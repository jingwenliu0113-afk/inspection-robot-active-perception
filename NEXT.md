# NEXT

## 目前位置（2026-10-13）

**Core 結案（decision 014）。Advanced B 已由使用者核准（方案 1，decision 015），目前在 B0 可行性驗證。Advanced C 暫不進行。**

GitHub：https://github.com/jingwenliu0113-afk/inspection-robot-active-perception（private，不加 LICENSE——使用者 2026-10-13 決定）。每個 milestone commit 後 push。

| 階段 | 內容 | 狀態 |
|---|---|---|
| M0–M5 | Core v1（平台、world、detector、pilot、調參、凍結、正式 test、Gate） | 完成（decision 001–010） |
| v2 | decision-v2、rule-nbv-v2、oracle-v2；train 調參、val 檢查；holdout 一次性比較 | 完成（decision 011–013） |
| Core 結案 | Gate 總表、改善歸因、failure analysis、資料封存 | 完成（decision 014） |
| B0 | Nav2 映像、官方 TB4 smoke、桅桿相機 TB4、`gen-nav-b0`、driver、分析；12 集 | 完成：C1–C5 通過、C6 未通過（decision 015 附錄 B） |
| decision 016 | 位姿精修 + 看穿餘裕；`nav-b0c` 確認：安全通過、C3 86.1% 未過 → 使用者「再試一次」→ 停點視角重定位 → `nav-b0d` 確認 | **B0 全部通過**（decision 016 附錄 D、`results/nav-b0d/`） |
| B1 | 閉迴路整合：`inspection-ap-navdet`、四方法 + Nav2、teleport 對照、新指標、`nav-b1` 開發資料 | **進行中**（decision 017） |

### 目前狀態

- B0 通過：`nav-b0d` 準確到點 100%、重定位後定位 p95 0.42 cm / 0.0021 rad、錯誤答案 0、geometric risk 0、聯集 0 / 6；代價 7 / 84 absent 組合變 inconclusive。
- B1 依 decision 017 進行；B2 正式評估前要先寫 decision 018。
- 容器關閉時 exit 139 為無害的關閉階段 segfault。

## 主要結果

- v1 原 test（524 ep）：Rule 0.706 / 0.996（budget 2 / 3），Random 0.620 / 0.907；Oracle − Rule 0.004。
- holdout（600 ep）v1：Rule 0.683 / 0.968，Random 0.608 / 0.898；**Oracle − Rule 0.028 / 0.032 → 原 test 的「接近 Oracle」未重現**。
- holdout v2：Rule **0.957 / 0.998**，Random 0.868 / 0.975，Single 0.392，Oracle 1.0 / 1.0；所有方法 false-absent = 0；ECE ≤ 0.008。
- **v2 的改善主要來自 absent 判定規則，不是 NBV 策略**：判定規則 +0.253（修好 152、弄壞 0）；策略 +0.020 [−0.020, 0.058]（修好 31、弄壞 19，不顯著）。
- Gate 未通過：v1 Gate 4 在 holdout；v2 Gate 4 在 budget 2（Oracle − Rule 0.043 [0.020, 0.070]）。
- failure analysis：v1 budget 2 失敗約 90% 是結構性（Oracle 也失敗）；v2 殘餘失敗 100% 可歸因於視角選擇；
  rule-nbv-v2 在初始視角被擋時 75–81% 的第二視角決策是平手、按候選編號選（開發資料）。

## 待使用者決定

1. **Advanced C（RL）**：使用者決定暫不進行。
2. 任何新版本都需要新的 namespace 與未參與開發的資料；`core` test 與 `holdout` 已封存。
3. 實體機器人（SPEC Optional）：需採購與 sim-to-real 感知驗證，另外決定。
4. Advanced B 進行中，沒有待決項目；若 B1 / B2 需要研究設計變更會先詢問。

## 已驗證的事實（不要重做）

- Gazebo depth 是 **planar depth**（與 ray-cast 比對：中位誤差 0.25 mm、p99 0.5 mm），非物件像素 label 一致 99.98%。
- 同 pose 重 render、跨 server、10 Hz vs 30 Hz：RGB / depth / labels **逐像素相同**。
- Python gz bindings 不可訂閱 `/world/<w>/clock`（約 250 Hz，會讓服務請求逾時並在結束時 segfault）。
- `remove/blocking` 在平行容器下偶爾回 false → clear pass 改用 `set_pose_vector` 停放柱子（與移除逐像素相同）。
- detsel 上三個 detector 主指標飽和（AUROC 1.0），由授權 tie-break 選 FRCNN（decision 005 附錄 B）。
- FRCNN 在 Mac CPU / MPS 與 CUDA 的最高 confidence 差 ≤ 5e-4（容器 CPU ≤ 0.004）。
- replay world 必須 memoize 觀測，否則調參每次 run 都重讀 npz（6 ms → 25 µs）。

## Blocked / 注意事項

- **跨專案**：`rtu-maintenance-platform` 的流程在停掉自己的 DB 容器後會關閉 Docker Desktop（2026-10-13 11:33、15:01、16:01，看起來每小時一次；supervisor log 可見）。
  本專案 render 會被中斷，但可續跑（已完成的 episode 自動跳過，單一 episode 失敗會重試）。本專案只重新啟動 Docker Desktop，從不碰其他專案的容器。
- Mac 從 GitHub release 下載大檔不穩（兩次截斷）；權重一律以官方 digest 驗證，必要時從 gpu-server 串流回來。
- Mac ↔ gpu-server 傳輸約 0.6 MB/s（760 MB 約 21 分鐘）。
- gpu-server：`~/ai-portfolio/inspection-robot-active-perception`，`.venv-det`（torch 2.13.0+cu130，全部由 uv 快取離線安裝），不動 Ubuntu-22.04 系統環境。

## 已知 SPEC 差異

- SPEC §2 `visible` 寫「初始/可達視角可觀測」；實作採「初始視角」定義，「可達」另記為 `revealable`（decision 002）。core 中 revealable 皆為真（沒有「所有候選都看不到」的 present episode）。
- SPEC §3 寫 Nav2 放 Advanced：維持。ROS 2 在 Core 只做 teleport 與系統整合（decision 001 附錄 B / D）。

## 本 session 完成的事（2026-10-13，含 v2 與 Core 結案）

- M2–M5 全部：Docker 映像與 smoke test、decision 005–010、gen-v2 消防栓 world、render-then-replay、depth / label sensing、
  detector 選型（RTX 5070 Ti、GPU lock）、pilot 六項 + ROS 2 線上一致性、core 1200 ep、調參、凍結、正式 test、Gate 判定、README 結果與圖。
- GitHub private repo 建立並 push。
- v2：decision 011（設計 / 資料 / 協定）、附錄 A（train 上修正位置密度）、012（凍結）、013（holdout 結果）；
  `decision-v2`、`rule-nbv-v2`、`oracle-v2`、`frozen_v2`、`experiment_v2`、v2 tests、v1 回歸測試（val 數字逐位元重現）。
- holdout 渲染、GPU 偵測、一次性比較；README 新增 v2 段落與圖（v1 段落數字未改）。
- Advanced B0：decision 015（協定 + 附錄 A 整合調整 + 附錄 B 結果）、`Dockerfile.nav`、`activeperception/nav/`、`docker/nav_smoke.sh` / `nav_b0.sh`、`tests/test_nav_b0.py`、`results/nav-b0/`。
- Core 結案：decision 014；`failure_analysis.py`（只讀已 commit 結果 + 開發資料平手分析）、`docs/failure-analysis.md`、`failure_attribution.png`；
  `seal.py` + `SEALED.sha256` + `tests/test_seal.py`（正式 runner 對封存資料只允許 `--reproduce`）；Advanced B 評估（唯讀容器檢查 Nav2 套件）。
