# NEXT

## 目前位置（2026-10-10）

**Core，M1 完成、M2 前置（Dockerfile / SDF world 產生器 / detector 介面）完成，M2 實際建置等使用者核准下載。** 尚無正式結果。

| Milestone | 內容 | 狀態 |
|---|---|---|
| M0 | repo init、環境稽核、decision 001 | 完成 |
| M1 | task definition 凍結（002–004）、episode generator、synthetic world、harness、4 policies、grader、metrics、69 tests | 完成 |
| M2 | Gazebo Harmonic + ROS 2 Jazzy 容器（Dockerfile 釘版本）、headless render smoke test、teleport（set_pose）determinism、camera intrinsics 記錄 | 前置完成（`docker/`、`sim/sdf.py`、`detector/`）；**建置 blocked：需使用者核准 > 1 GB 下載** |
| M3 | minimal world（zone、物件、方柱遮擋物、RGB-D camera）、GazeboObservationSource、GT visibility（segmentation / depth）、detector 整合 | 待 M2 與 detector 決策 |
| M4 | pilot（SPEC §9）：三狀態可分、teleport deterministic、timestamp / transform、四方法同候選集、grader 不吃掉 inconclusive | 待 M3 |
| M5 | 在 train / val 調 decision rule 與 rule-NBV 參數 → decision log 凍結 budget / 參數 → 正式 test → metrics + CI → README 結果 | 待 M4 |
| Gate | Rule 穩定勝過 Random / Single、非 leakage、仍有可重現殘餘失敗 → 才考慮 Advanced | 待 M5 |

## 下一步（依序）

1. **等使用者回覆兩件事**（見本次 session 結尾摘要）：
   - 是否核准在 Mac Docker 拉 `ros:jazzy-ros-base`（arm64，約 0.3 GB）並 apt 安裝 `ros-jazzy-ros-gz` + `gz-harmonic`（約 1 GB 以上）。
   - Core detector 選型（decision 005 待寫）：候選為 (a) 預訓練 COCO detector（如 ultralytics YOLO，CPU 推論）配 Gazebo Fuel 的 COCO 類別物件；(b) 古典顏色 / 形狀 detector（完全決定性，但 confidence 語意較弱）；(c) open-vocabulary detector（較重，可能需 GPU）。建議 (a)。
2. 核准後 M2：`./docker/build.sh` → `./docker/run.sh bash docker/smoke.sh`；驗證 headless render 產出 RGB + depth、`set_pose` teleport 生效、同 pose 兩次 render 逐像素相同；`./docker/run.sh bash docker/record_versions.sh` 把版本寫進 `docs/platform/versions.md`，Dockerfile 改釘 base digest，commit。
3. 若 arm64 ogre2 headless 失敗：同一份 Dockerfile 改在 `gpu-server` Docker Desktop 以 amd64 建（decision 001 方案 B），CPU 渲染。
4. M3：`activeperception/sim/gazebo.py` 實作 `ObservationSource`（set_pose teleport → 等待新 frame → detector → `Observation`；`zone_visible_fraction` 由 depth 計算；oracle pass 用 segmentation camera 算 GT visibility，走同一個 `labeling.py`）。
5. 不需等 M2 也能做的 Core 工作（若使用者尚未回覆）：
   - 在 synthetic world 上做 decision rule / rule-NBV 的敏感度分析腳本（只用 train / val，純工程驗證，不是結果）。
   - `docs/EXPERIMENT_RULES.md` 補 pilot checklist 對應的自動化檢查。

## Blocked / Deferred

- **M2 Gazebo image 下載**：等核准（> 1 GB）。
- **GPU**：目前不需要。2026-10-10 12:00 實測 RTX 5070 Ti 被其他 Project 使用中（5.3 GB / 52%），lock 檔存在；本 Project 在 Advanced 前都不碰 GPU。

## 已知 SPEC 差異

- SPEC §2 `visible` 寫「初始/可達視角可觀測」；實作採「初始視角」定義，「可達」另記為 `revealable`（decision 002）。若要改回，需另開 decision log。

## 本 session 完成的事（2026-10-10）

- `git init -b main`，`.gitignore`、`pyproject.toml`（uv, Python 3.12）、README。
- 環境稽核：Mac 無 ROS/Gazebo；Docker Desktop arm64 可用；`ros:jazzy-ros-base` 有 arm64；ROS / OSRF apt 均有 noble arm64 的 `ros-jazzy-ros-gz` 與 `gz-harmonic`；`gpu-server` 可連，WSL 只有 `Ubuntu-22.04`，`Ubuntu-24.04` 可安裝。
- decision 001–004。
- `activeperception/`：types、geometry、episodes、labeling、serialize、sim/synthetic、decision、policies ×4、harness、grader、metrics、cli。
- 76 tests 全綠（determinism、leakage tripwire、budget、grader 真值表、metrics、serialize、CLI、SDF 產生器、detector 介面）。
- M2 前置：`docker/Dockerfile`（Jazzy ros-base + OSRF gz-harmonic + Mesa/EGL/Xvfb）、`build.sh` / `run.sh` / `smoke.sh` / `grab_frames.py` / `record_versions.sh`、`activeperception/sim/sdf.py`（EpisodeSpec → SDF world，含 RGB / depth / segmentation camera 與 label plugin）、`activeperception/detector/`（介面 + test double）。
- synthetic smoke sweep 確認 budget=1 時四方法輸出一致、無 false absent、oracle ≥ rule/random ≥ single（pipeline sanity，不是結果）。
