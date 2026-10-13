# 001 — 正式模擬平台與執行環境

- **日期**：2026-10-10
- **狀態**：已決定（環境方案待使用者核准下載後執行 smoke test）
- **是否在看過正式結果後才新增 / 修改**：否，尚無任何正式結果。

## 問題

SPEC 固定平台為 ROS 2 Jazzy + Gazebo Harmonic（Ubuntu 24.04）。手邊沒有任何現成的 24.04 / Jazzy 環境：

| 機器 | 現況（2026-10-10 實測） |
|---|---|
| Mac（Apple Silicon, 48 GB, 12 核） | 無 ROS / Gazebo；Docker Desktop 29.8 可用（arm64 VM 12 CPU / 15.6 GiB）；Python 3.12 via uv |
| `gpu-server`（Windows 11 + WSL2 2.7.3） | distro 只有 `Ubuntu-22.04`（RTX 5070 Ti，供 Text-to-SQL / Serving Lab 共用）與一個停用的 `Ubuntu`；`Ubuntu-24.04` 可從 `wsl --list --online` 安裝；C: 剩 1.2 TB |

套件可得性（只查 index，未下載）：

- `ros:jazzy-ros-base` 官方映像有 **arm64**（287 MB compressed）；`osrf/ros:jazzy-desktop-full` / `jazzy-simulation` 只有 amd64。
- ROS apt repo（noble, arm64）有 `ros-jazzy-ros-gz 1.0.24`、`ros-jazzy-gz-sim-vendor 0.0.13`、`ros-jazzy-ros-base 0.11.0`。
- OSRF apt repo（noble, arm64）有 `gz-harmonic 1.0.0`、`libgz-sim8 8.15.0`、`libgz-rendering8 8.3.0`。

## 候選方案

| 方案 | 做法 | 優點 | 缺點 |
|---|---|---|---|
| **A. Mac Docker（arm64）** | 自寫 Dockerfile：`ros:jazzy-ros-base` + `ros-jazzy-ros-gz`；`gz sim -s --headless-rendering`，Mesa llvmpipe 軟體渲染 | 不需 sudo、不碰 gpu-server、與開發同機、版本以 image digest 釘死、軟體渲染無 GPU driver 非決定性 | 渲染慢（Core 影像量小，可接受）；arm64 + ogre2 需實測 |
| B. gpu-server Docker Desktop（amd64） | 同一份 Dockerfile 在 Windows Docker Desktop 以 amd64 建置，CPU 軟體渲染 | x86_64 是 ROS Tier 1，最保險 | 占用共享機器資源；WSL2 內 GPU 渲染走 Mesa d3d12，ogre2 相容性不穩，故不追求 GPU 渲染 |
| C. 新 WSL distro `Ubuntu-24.04` | `wsl --install -d Ubuntu-24.04`，apt 裝 Jazzy + Harmonic | 原生環境、可用 WSLg 開 GUI 除錯 | 需使用者互動建立帳號與 sudo；與 Ubuntu-22.04 共用 Windows 資源 |
| D. Mac VM（Lima / Multipass） | Ubuntu 24.04 arm64 VM | 原生 apt | 需另裝 VM 工具（Multipass 要 admin）；比 Docker 多一層管理 |

## 最終選擇

**A 為主要平台，B 為備援；C/D 不採用，除非 A 與 B 都失敗。**

理由：

1. Core 是 teleport-based，每個 episode 最多 5 張影像，數千張靜態渲染在軟體渲染下仍是分鐘到小時等級，不需要 GPU。
2. 平台記錄（OS / ROS / Gazebo 版本）以 Dockerfile + image digest 釘死，比手動 apt 的 VM 更可重現。
3. 完全不碰 `Ubuntu-22.04` GPU WSL，符合 MACHINE_POLICY。
4. 若 arm64 下 ogre2 無法 headless 渲染，同一份 Dockerfile 直接在 gpu-server 以 amd64 建置（方案 B），實驗程式碼不變。

## 正式平台的版本記錄義務

正式 pilot 之前必須記錄並 commit：Dockerfile、image digest、`ros-jazzy-*` 與 `gz-*` 套件版本清單、world / model revision、camera intrinsics / extrinsics、random seed、generator version。

## Synthetic world 的定位

`activeperception/sim/synthetic.py` 是解析幾何的替身世界，只用於：

- correctness tests（determinism、leakage、budget、grader）
- policy / decision rule 的開發除錯

**synthetic world 的任何數字都不是研究結果，不得出現在 README 結果區或 Gate 判斷中。** 正式結果只能來自 Gazebo Harmonic world。

## 被此決策凍結的項目

- 正式平台：ROS 2 Jazzy + Gazebo Harmonic，容器化，image digest 釘死。
- 渲染：headless 軟體渲染（除非之後另開 decision log 改變）。
- GPU 只用於 detector training / heavy batch inference（Advanced），且須遵守 `/tmp/ai-portfolio-gpu.lock`。

## 附錄 A（2026-10-10）：容器內容與套件來源

查 apt index 後確認：

- Jazzy 的 `ros-jazzy-gz-*-vendor` 套件**自帶** Harmonic 二進位（只依賴系統函式庫與其他 vendor 套件，不依賴 OSRF 的 `libgz-sim8`）。所以 `ros-jazzy-ros-gz` 單獨就能帶入 Harmonic，但其 `gz` 工具與 Python bindings 位於 `/opt/ros/jazzy/opt/*` 的非標準路徑。
- OSRF repo 的 `gz-harmonic` metapackage（arm64 / amd64 皆有）提供標準路徑的 `gz` CLI、`python3-gz-transport13`、`python3-gz-msgs10`、`python3-gz-sim8`。

`docker/Dockerfile` 採：`ros:jazzy-ros-base`（提供 ROS 2 Jazzy 平台）+ OSRF `gz-harmonic` + Python bindings + Mesa / EGL / Xvfb。
Core 的 teleport harness 直接用 gz-transport（`/world/inspection/set_pose` 服務與 `/inspector/*` 影像 topic），不經 `ros_gz_bridge`，減少非決定性來源。
`ros-jazzy-ros-gz` 留到 Advanced B（Nav2）需要 ROS 端橋接時再加入，屆時另記錄版本。

預估下載：base 約 0.3 GB（compressed）+ `gz-harmonic` 及依賴約 1 GB 以上；需使用者核准。

Smoke test 腳本（`docker/smoke.sh`、`docker/grab_frames.py`）與 SDF 產生器（`activeperception/sim/sdf.py`）已寫好；SDF 產生器有單元測試，容器腳本在 image 建好前未經執行。

## 附錄 B（2026-10-13）：改用 ROS vendor 套件，ROS 2 進入 Core 系統整合

**背景**：使用者 2026-10-13 指示專案採「研究＋實用兼顧」：Core 必須透過 ROS 2 + Gazebo 運作（Mac M4 Pro 負責 ROS 2 / Gazebo / 模擬與系統整合）。附錄 A 把 `ros-jazzy-ros-gz` 延到 Advanced B 的安排因此改變。

**實測（`ros:jazzy-ros-base` arm64，digest `sha256:066420e07f60aa18262f2479981def87ebcfcec42eefb0c0c57c4a46098348ca`）**：
`ros-jazzy-ros-gz-sim ros-jazzy-ros-gz-bridge ros-jazzy-ros-gz-image ros-jazzy-vision-msgs` 共 596 個套件、壓縮下載約 316 MB；
其中 `ros-jazzy-gz-*-vendor` 已帶入 Harmonic（gz-sim 8、gz-rendering 8 / ogre2、gz-sensors 8、gz CLI），
`ros-jazzy-gz-transport-vendor` 依賴 `pybind11-dev`（Python bindings 一併建置）。

**決定**：

- Dockerfile 改為只用 packages.ros.org 的 vendor 套件，不再另裝 OSRF `gz-harmonic`，避免同一映像內有兩份不同小版本的 Harmonic 函式庫與 plugin。這是 ROS 2 Jazzy 官方的 Jazzy + Harmonic 配對方式。
- ROS 2 在 Core 的角色：`ros_gz_bridge` 橋接相機影像與 `set_pose` 服務，ROS 2 node 以**同一套** decision rule / policy 程式碼線上執行巡檢（系統整合與 demo）。
- 正式指標的資料來源仍是同一個 Gazebo world 的**決定性 render**（見 decision 007），ROS 2 線上執行需與離線 replay 的決策一致（pilot 檢查項）。這樣 ROS 2 訊息時序不會成為實驗的非決定性來源。
- apt 套件無法長期釘版本（ROS apt repo 只保留最新版），可重現性以「base digest + 建好映像的 image ID + `docs/platform/versions.md` 套件版本清單」為準。

**是否在看過正式結果後才修改**：否，尚無任何結果。

## 附錄 C（2026-10-13）：M2 smoke test 通過，方案 A 確認

`inspection-ap-sim:jazzy-harmonic`（image id `sha256:49d6e69b240a…`，套件清單見 `docs/platform/versions.md`）在 Mac arm64 Docker 上：
headless ogre2 渲染 RGB / depth / segmentation 正常、`set_pose` teleport 生效、同 pose 重 render 逐像素相同、每 viewpoint 約 0.3 s。
細節見 `docs/platform/m2-smoke.md`。方案 B（gpu-server amd64）不需要。

## 附錄 D（2026-10-13）：ROS 2 線上整合映像與驗證

- `docker/Dockerfile.ros` 在 render 映像之上加 CPU 版 torch / torchvision（inspector node 在迴圈中跑 detector-v1）；正式 render 映像不變。
- ROS 2 graph：`gz sim`（headless）+ `ros_gz_bridge parameter_bridge`（`/inspector/rgb`、`/inspector/depth` → `sensor_msgs/Image`；
  `/world/inspection/set_pose/blocking` ↔ `ros_gz_interfaces/srv/SetEntityPose`）+ `inspection_ap_ros/inspector`（`ros_ws/src/inspection_ap_ros`）。
- 驗證：pilot 24 episodes × 8 個 (policy, budget) 的線上執行與 replay 的 viewpoint 序列、決策 192/192 相同（`results/pilot/`）。
