# 007 — Gazebo 觀測管線：決定性 render → frame store → replay；depth / segmentation 的量測定義

- **日期**：2026-10-13
- **狀態**：已決定（pilot 會驗證；pilot 發現的修正另開 decision log）
- **是否在看過正式結果後才新增 / 修改**：否。

## 問題

decision 002 / 004 把 `zone_visible_fraction`（部署可得）與 GT visibility（只給 grader / oracle）定義在 synthetic world 的解析幾何上，
並註明 Gazebo 版「之後用 depth / segmentation 實作」。現在要把它們落實在 Gazebo Harmonic，同時滿足：

- SPEC §3：teleport / deterministic pose placement，四個方法吃到相同候選 viewpoint。
- SPEC §9：teleport deterministic、sensor timestamp / transform 正常。
- 使用者 2026-10-13 的方向：ROS 2 + Gazebo 實際運作（研究＋實用兼顧，decision 001 附錄 B）。

## 候選方案

| 方案 | 說明 | 取捨 |
|---|---|---|
| A. 線上閉環 | 每個 method × budget × episode 都即時 teleport → render → detect | 同一 viewpoint 會被不同 method 重複 render；任何 render / 時序抖動都會讓 method 間比較混入噪音；成本 ×（methods × budgets） |
| **B. render-then-replay** | 每個 episode 的 13 個 viewpoint（初始 + 12 候選）各 render 一次存進 frame store；detector 對每張 frame 跑一次並快取；harness 對所有 method 重播同一份觀測 | 觀測與走訪順序無關（teleport 的語意本來就如此）；四個方法保證看到逐位元相同的觀測；成本最低；可事後重算 |

## 決定：方案 B，ROS 2 線上閉環作為整合驗證

### Render（容器內，gz-transport）

- 每個 episode 產生兩個 SDF：**full**（完整場景）與 **clear**（移除所有遮擋柱，只在物件存在時需要）。
- 對每個 viewpoint：`/world/inspection/set_pose` 移動 `inspector_cam` → 只接受 header stamp 晚於 pose 生效時間的 frame → 存 RGB（uint8）、depth（float32 → 以 mm 存 uint16，無回波記為 65535）、semantic labels（uint8）。
- clear pass 只存 labels。
- 每個 frame 記錄：請求的 pose、sim time stamp、render 設定、image ID、SDF 版本。
- frame store 目錄：`renders/<render_set>/<episode_id>.npz` + `manifest.json`（大型資料，不進 git）。

### 部署可得的觀測（`Observation`）

- `detections`：選定 detector（decision 005）對 RGB frame 的結果；每個 detector 版本一份快取。
- `zone_visible_fraction`：zone 圓柱內取樣點（48 個圓盤點 × 3 個高度）投影到 depth 影像；若量測深度 ≥ 該射線**進入 zone 圓柱處**的深度 − 0.05 m，記為「未被 zone 外的東西擋住」；視野外的取樣點算被擋。
  以「進入 zone 的深度」而非「取樣點本身的深度」比較，是為了只量測 **zone 外的遮擋**：zone 內的物體（包含目標本身）不會降低這個值，避免它變成物件存在與否的間接訊號。
  synthetic world 的對應定義（相機到取樣點的線段被遮擋柱擋住）在 gen-v2 下等價，因為遮擋柱保證不侵入 zone（decision 006）。
- `timestamp`：render 的 sim time。

### GT（離線，只給 grader / Oracle NBV）

- `vis_fraction(vp)` = full pass 中 object label 像素數 / clear pass 中 object label 像素數。
- `area_frac(vp)` = clear pass object 像素數 / 影像像素數；`visibility = vis_fraction × min(1, area_frac / 0.002)`。
  這是 label-v1「可見表面比例 × 投影面積懲罰」在影像空間的實作；門檻與 `labeling.py` 不變。
- `zone_visible_by_viewpoint`：與部署觀測相同的 depth 推導量（它本來就不是 GT-only 資訊）。
- labels / clear pass 只能經由 `ground_truth()` 讀取；deployable policy 永遠拿不到（leakage tripwire test 涵蓋 replay world）。

### 驗證（pilot 項目）

1. **teleport determinism**：同一 episode 重 render 一次，RGB / depth / labels 逐像素比較。
2. **transform / intrinsics**：以 numpy 解析 ray-cast（同一份 episode 幾何、物件以包圍圓柱近似）產生 depth，與 Gazebo depth 在遮擋柱與地面像素上比較；驗證 pose 慣例、hfov、principal point 與 depth 定義（planar 或 range）。
3. **timestamp**：每個 frame 的 stamp 必須晚於對應 set_pose；同一 episode 內 stamp 單調遞增。
4. **ROS 2 線上一致性**：ROS 2 node 以同一套 decision rule / policy 在 live Gazebo 跑 pilot episodes，決策與 viewpoint 序列需與 replay 相同。

## 被凍結的項目

render-then-replay 協定、frame 內容與編碼、`zone_visible_fraction` 的 depth 定義（zone-entry 比較、0.05 m 容忍、144 取樣點）、
Gazebo GT visibility 的像素定義、labels 只經 `ground_truth()` 讀取。
