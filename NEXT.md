# NEXT

## 目前位置（2026-10-13）

**Core。M2–M4 完成（pilot 六項 + ROS 2 線上一致性全過）；M5 調參工具與 rule-NBV v1 特徵已實作，等 core render / detection 後跑 train 調參。** 尚無正式結果。

GitHub：https://github.com/jingwenliu0113-afk/inspection-robot-active-perception（private，2026-10-13 依使用者要求建立）。每個 milestone commit 後 push。

| Milestone | 內容 | 狀態 |
|---|---|---|
| M0 | repo init、環境稽核、decision 001 | 完成 |
| M1 | task definition（002–004）、generator、synthetic world、harness、4 policies、grader、metrics | 完成 |
| M2 | Jazzy + Harmonic 容器（ROS vendor 套件、base digest 釘死）、headless render、teleport、determinism | **完成**（`docs/platform/m2-smoke.md`、decision 001 附錄 B/C） |
| M3a | world gen-v2（消防栓、decision 006）、render-then-replay（decision 007）、depth / label sensing、frame store、replay world | **完成** |
| M3b/c | detector 候選、選型（decision 005）→ `detector-v1` = torchvision FRCNN-MobileNetV3 | **完成**（`results/detector-selection/`） |
| M3d | ROS 2 線上整合（ros_gz_bridge + inspector node） | **完成**（pilot 192/192 與 replay 相同） |
| M4 | pilot（SPEC §9）六項 + ROS 2 一致性 | **完成**（`results/pilot/`） |
| M5 | train / val 調參 → decision log 凍結 budget / 參數 → 正式 test → metrics + CI → README | 待 M4；**budget 最終值需使用者決定** |
| Gate | Rule 穩定勝過 Random / Single、非 leakage、仍有可重現殘餘失敗 | 待 M5 |

## 下一步（依序）

1. core render 完成 → `build-episodes --world gazebo` → `data/episodes/gazebo-core.json` commit。
2. core frames 傳到 gpu-server，`detector-v1` 在 GPU lock 下產生 `runs/core/detector-v1.jsonl`（同時存一份到 `results/` 以保留出處）。
3. decision 008 階段 1（`python -m activeperception.tune decision ...`）→ 階段 2（`tune rule`）→ 階段 3（`tune val`）。
4. 寫 decision 009：`decision-v1`、`rule-nbv-v1` 參數；**budget 組合請使用者確認**（附 val success-vs-budget 曲線），之後才跑 test。
5. test 一次：四方法、凍結 budgets、cluster bootstrap CI、分層結果 → README 結果區 → Gate 判斷。

## 已驗證的事實（不要重做）

- Gazebo depth 是 **planar depth**（與 ray-cast 比對：中位誤差 0.25 mm、p99 0.5 mm），非物件像素 label 一致 99.98%。
- 同 pose 重 render、跨 server、10 Hz vs 30 Hz：RGB / depth / labels **逐像素相同**。
- Python gz bindings 不可訂閱 `/world/<w>/clock`（約 250 Hz，會讓服務請求逾時並在結束時 segfault）。
- `remove/blocking` 在平行容器下偶爾回 false → clear pass 改用 `set_pose_vector` 停放柱子（與移除逐像素相同）。
- detsel 上三個 detector 的主指標飽和（AUROC 1.0），由授權 tie-break 選 FRCNN（decision 005 附錄 B）。

## Blocked / 注意事項

- **跨專案**：`rtu-maintenance-platform` 的流程在停掉自己的 DB 容器後會關閉 Docker Desktop（2026-10-13 11:33、15:01 各一次，supervisor log 可見）。
  本專案 render 會被中斷，但可續跑（已完成的 episode 自動跳過）。本專案只重新啟動 Docker Desktop，從不碰其他專案的容器。
- Mac 從 GitHub release 下載大檔不穩（兩次截斷）；權重一律以官方 digest 驗證，必要時從 gpu-server 串流回來。
- gpu-server：`~/ai-portfolio/inspection-robot-active-perception`，`.venv-det`（torch 2.13.0+cu130，全部由 uv 快取離線安裝，未做大型下載），不動 Ubuntu-22.04 系統環境。

## 已知 SPEC 差異

- SPEC §2 `visible` 寫「初始/可達視角可觀測」；實作採「初始視角」定義，「可達」另記為 `revealable`（decision 002）。
- SPEC §3 寫 Nav2 放 Advanced：維持。ROS 2 在 Core 只做 teleport 與系統整合（decision 001 附錄 B），不引入 Nav2。

## 本 session 完成的事（2026-10-13）

- M2：映像建置與 smoke test、平台版本記錄、decision 001 附錄 B / C。
- decision 005（detector 選型協定 + 結果）、006（gen-v2 消防栓 world）、007（render-then-replay 與量測定義）。
- `sensing`、`sim/raycast`、`sim/gz_client`、`sim/render`、`framestore`、`sim/replay`、`detector/{cache,models,run,evaluate}`。
- detsel（160 ep）與 pilot（24 ep）render + GT；detector 選型在 RTX 5070 Ti（GPU lock）完成。
- tests 117 個全綠。
