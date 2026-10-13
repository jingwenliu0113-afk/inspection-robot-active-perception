# NEXT

## 目前位置（2026-10-13）

**Core v1 完成。正式 test 已跑一次，Gate 已判定（decision 010）：Rule-based NBV 穩定勝過 Single / Random，且已接近 Oracle → 依 SPEC 不做 RL。**
**所有 Core 工作已完成；下一步需要使用者決定（見「待使用者決定」）。**

GitHub：https://github.com/jingwenliu0113-afk/inspection-robot-active-perception（private）。每個 milestone commit 後 push。

| Milestone | 內容 | 狀態 |
|---|---|---|
| M0 | repo init、環境稽核、decision 001 | 完成 |
| M1 | task definition（002–004）、generator、synthetic world、harness、4 policies、grader、metrics | 完成 |
| M2 | Jazzy + Harmonic 容器（ROS vendor 套件、base digest 釘死）、headless render、teleport、determinism | 完成（`docs/platform/`） |
| M3 | world gen-v2（消防栓）、render-then-replay、depth / label sensing、detector 選型 `detector-v1`、ROS 2 線上整合 | 完成 |
| M4 | pilot（SPEC §9）六項 + ROS 2 線上 = replay（192 / 192） | 完成（`results/pilot/`） |
| M5 | core set 1200 ep、train 調參（decision 008）、val 檢查、凍結 v1（009）、test 一次 | 完成（`results/test-v1/`） |
| Gate | decision 010：1–3 成立；rule ≈ oracle → 不做 RL；perception 非瓶頸 → 不做 detector fine-tune | **已判定** |

## 主要結果（core test，524 episodes）

budget 2 / 3 accuracy：Single 0.202 / 0.202、Random 0.620 / 0.907、**Rule 0.706 / 0.996**、Oracle 0.710 / 1.000。
Rule − Random：+0.086 [0.072, 0.101] / +0.089 [0.069, 0.108]。false absent：Rule 0、Random 0.0015。

## 待使用者決定

1. **Advanced B（Nav2）要不要做**：Gate 1–3 成立，技術上允許，但 Advanced 不是自動下一步。若做，必須保留 teleport 結果作對照（SPEC Advanced B）。
2. **是否做 rule-NBV v2**（處理殘餘失敗 2：未觀測格子的樂觀假設，`core-g0298`）：只能以新版本在新一輪 test 報告，v1 結果保留。
3. **Optional**（真實相機、domain randomization 等）只在使用者明確要求時做。
4. repo 目前 private；是否公開、是否加 LICENSE（vendored 模型為 CC0；若未來改用 Ultralytics 會有 AGPL 義務）。

## 可以不需決策就做的整理（低優先）

- README 失敗案例改成 GIF（目前為 PNG）。
- 把 `tools/make_figures.py` 的圖加上 CI 誤差條（目前 CI 在表格中）。

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

## 本 session 完成的事（2026-10-13）

- M2–M5 全部：Docker 映像與 smoke test、decision 005–010、gen-v2 消防栓 world、render-then-replay、depth / label sensing、
  detector 選型（RTX 5070 Ti、GPU lock）、pilot 六項 + ROS 2 線上一致性、core 1200 ep、調參、凍結、正式 test、Gate 判定、README 結果與圖。
- GitHub private repo 建立並 push。
