# NEXT

## 目前位置（2026-10-13）

**Core。M2 完成、M3 大部分完成（render → replay 管線、detector 選型凍結 `detector-v1`），正在進 M4 pilot。** 尚無正式結果。

| Milestone | 內容 | 狀態 |
|---|---|---|
| M0 | repo init、環境稽核、decision 001 | 完成 |
| M1 | task definition（002–004）、generator、synthetic world、harness、4 policies、grader、metrics | 完成 |
| M2 | Jazzy + Harmonic 容器（ROS vendor 套件、base digest 釘死）、headless render、teleport、determinism | **完成**（`docs/platform/m2-smoke.md`、decision 001 附錄 B/C） |
| M3a | world gen-v2（消防栓、decision 006）、render-then-replay（decision 007）、depth / label sensing、frame store、replay world | **完成** |
| M3b/c | detector 候選、選型（decision 005）→ `detector-v1` = torchvision FRCNN-MobileNetV3 | **完成**（`results/detector-selection/`） |
| M3d | ROS 2 線上整合（ros_gz_bridge + inspection node，與 replay 一致性） | 待做 |
| M4 | pilot（SPEC §9）：三狀態可分、teleport deterministic、timestamp / transform、四方法同候選集、grader 不吃 inconclusive | 進行中 |
| M5 | train / val 調參 → decision log 凍結 budget / 參數 → 正式 test → metrics + CI → README | 待 M4；**budget 最終值需使用者決定** |
| Gate | Rule 穩定勝過 Random / Single、非 leakage、仍有可重現殘餘失敗 | 待 M5 |

## 下一步（依序）

1. pilot detection 快取：`frcnn-mnv3` 在 gpu-server（GPU lock）跑 `renders/pilot`。
2. pilot 自動檢查（`activeperception/pilot.py`）：三狀態分佈與可分性、teleport determinism（重 render 比對）、
   stamp 晚於 teleport、depth vs ray-cast（已驗證 planar、中位誤差 0.25 mm）、四方法候選集相同、grader 真值表。
3. M3d：ROS 2 inspection node（同一套 decision rule / policy，經 ros_gz_bridge），pilot episodes 上與 replay 決策一致。
4. 正式 `core` namespace：決定 scene group 數（統計功效）→ make-specs → render → GT → detection 快取（GPU）。
5. train / val 上調 decision rule（τ_present / τ_absent / coverage）與 rule-NBV 權重，寫 decision log 凍結；budget 組合請使用者確認。

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
