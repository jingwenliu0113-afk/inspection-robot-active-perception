# 015 — Advanced B（Nav2）啟動與 B0 可行性驗證協定（預先登錄）

- **日期**：2026-10-13
- **狀態**：B0 協定凍結；寫於任何 Nav2 量測之前。B0 結果以本檔附錄記錄；B1 協定另寫 decision 016。
- **是否在看過正式結果後才新增 / 修改**：否——B 沒有任何結果。Core（decision 001–014）的結論、資料與 Gate 全部不變。

## 1. 使用者決定（2026-10-13）

1. 進入 Advanced B（Nav2），採**方案 1**分階段：B0 可行性 → 依既定標準決定是否進 B1 → B2 正式評估。
2. 核准建立所需 Docker 映像；**優先使用 Mac**，與其他專案資源隔離。
3. 模擬機器人優先用 **TurtleBot 4**；先驗證 Jazzy / Gazebo Harmonic 相容性；不購買實體機器人。
4. 使用**已凍結的 v2**（`frozen_v2.py`）；Core 的 v1 / v2、test、holdout 與 Gate 結果全部不變。
5. 重點：**導航成功率、定位誤差、觀察可靠性、導航失敗是否導致錯誤判斷**。**不得用 ground truth 作弊。**
6. 環境或研究設計需要重大變更時先詢問使用者。

## 2. 不變的部分

- `decision-v2`、`rule-nbv-v2`、`detector-v1`、64 個候選位置與 0.03 m 看穿容忍值、`CameraModel`（640×480、hfov 60°）不變，不重新調參。
- Core 的 `inspection-ap-sim` 映像不變；Nav2 用另一個映像 `inspection-ap-nav`（`docker/Dockerfile.nav`，以 sim 映像為底，apt 結果「0 upgraded」）。
- `core` test、`holdout` 已封存（decision 014）；B 不使用任何 Core 的 episode set。

## 3. Ground truth 使用規則（B 全程適用）

**可部署路徑**（導航目標、判定規則、視角策略）只能使用：

- 候選視角（只由 inspection zone 與 scene-group seed 決定，同 Core）；
- 機載相機的 RGB / depth、`detector-v1` 的輸出；
- **機器人估計的位姿**（AMCL 的 map → base_link）與已知的桅桿相機外參；
- 事先給定的設施地圖：牆、柱子、inspection zone 的禁入區。**地圖永遠不含巡檢目標**；同一 scene group 的 present / absent variants 使用同一張地圖。視角策略不讀地圖。

**只用於評分**（寫進獨立的 scoring 檔，可部署路徑的程式不得讀取）：

- Gazebo 的真實位姿（機器人、相機）、semantic segmentation、物件是否存在、GT 可見度。

程式強制：可部署的觀測建構函式不接受 GT 參數；地圖只由牆 / 柱子 / zone 產生（tests 檢查 present / absent 地圖逐位元相同）。
lidar 只供 Nav2 定位與避障，**不**進入判定規則或視角策略。

## 4. B0 範圍（可行性，不是研究結果）

- 映像：`inspection-ap-nav`（Nav2 1.3.x、`nav2_minimal_tb4_sim`、`nav2_minimal_tb4_description`）。
- 相容性 smoke：官方 TurtleBot 4 模擬（headless、無 GUI）在 Mac arm64 容器中啟動 Nav2 並完成導航。
- 機器人：TurtleBot 4 ＋ 桅桿相機（光心離地 1.1 m、往下 0.314 rad；RGB / depth / segmentation 三個感測器的內參同 Core `CameraModel`）。
- 場景草案 `gen-nav-b0`：同 gen-v2 的 zone、消防栓、柱子，另加 8 m × 8 m 圍牆；候選環固定半徑 2.0 m、高度 1.1 m；
  柱子與相機環的間隙 ≥ 0.35 m（機器人半徑約 0.175 m 加安全距離）。B1 可依 B0 結果修訂後凍結為 `gen-nav-v1`。
- 資料：新 namespace `nav-b0`，**只作可行性用**，永不作正式評估。6 個 scene groups × 2 variants（1 present、1 absent）= 12 episodes。
- 每個 episode：機器人從初始視角出發，依 seed 決定的順序導航到全部 12 個候選視角；另外插入 2 次「中途取消」的導航（依 seed 在預期行程的 20–80% 取消），
  在停下的地方拍攝——用來檢查導航失敗時判定是否仍安全。

## 5. B0 通過標準（預先登錄；全部成立才進 B1）

| # | 項目 | 標準 |
|---|---|---|
| C1 | 相容性 | Nav2 + TurtleBot 4 + Gazebo Harmonic 在 Mac arm64 容器 headless 運作；sim 映像的套件版本不變；每個 episode 的 Nav2 都能進入 active（暫時性啟動失敗可重試，次數照實報告） |
| C2 | 模擬速度 | 導航期間 real-time factor 中位數 ≥ 0.5 |
| C3 | 導航成功率 | 12 個候選視角的導航目標中，Nav2 回報成功**且**真實位置誤差 ≤ 0.10 m、朝向誤差 ≤ 0.10 rad 的比例 ≥ 90%；碰撞 0 次（以真實位姿與柱子 / 牆的幾何距離判斷） |
| C4 | 定位誤差 | 到點時 AMCL 估計 vs 真實位姿：位置誤差 p95 ≤ 0.10 m、朝向誤差 p95 ≤ 0.05 rad（中位數一併報告） |
| C5 | 觀察可靠性 | (a) 每次到點後都拿到時間戳晚於到點的機載影像（≥ 99%）；(b) 機載 depth 與「真實相機位姿下的解析 ray-cast」在靜態幾何像素上的中位絕對誤差 ≤ 0.01 m 的影像比例 ≥ 95%（確認機載相機與 Core 相機模型一致，凍結的 v2 感測可沿用）；(c) 報告消防栓可見像素與偵測的關係，與 Core 比較 |
| C6 | 導航失敗不導致錯誤判斷 | 只用可部署資料（估計位姿、機載影像、detector），對每個 episode 的「初始視角 + 任一到點視角」與「初始視角 + 任一中途取消視角」組合套用 `decision-v2`：**錯誤的肯定答案（false absent / false present）= 0**；以估計位姿計算的 geometric false-absent risk = 0 |

判定：

- C1–C6 全部成立 → 寫 decision 016（B1 協定）後進 B1。
- C2–C5 未達標：先做一般技術調整（Nav2 參數、感測器頻率、啟動流程），只用 `nav-b0` 資料，調整內容照實記錄；仍未達標 → 停在 B0，報告並詢問使用者。
- **C6 未成立**（導航誤差讓 v2 給出錯誤答案）→ 這代表需要研究設計上的變更（例如考慮位姿不確定性的看穿判定）→ **停下來詢問使用者**，不自行修改 v2。

## 6. 已知限制（先寫明）

- Gazebo 的差速里程計接近理想，定位誤差可能比實機樂觀；B1 是否加入里程計雜訊模型在 decision 016 決定。
- B0 只有 12 個 episodes，標準是可行性門檻，不是統計結論。

## 附錄 A（2026-10-13，B0 正式批次之前）：開發試跑與整合調整

在 `nav-b0-g0000-v0` 上做了一次開發試跑（`runs/nav-b0-dev/`，不計入 B0 結果），據此做了以下**整合層**調整（只動 Nav2 / 機器人設定，不動 v2）：

| 調整 | 原因 |
|---|---|
| 桅桿高度校正：`base_link` 靜止時在地面下 4 mm（`/gt/odom` 讀一次）→ 相機關節 1.104 m，使光心在 1.1 m | 固定的機器人校正（同實機 URDF 校正），不是執行時的 GT |
| 到點容忍值 0.05 → 0.07 m（朝向維持 0.05 rad） | 0.05 m 時 MPPI 在終點附近來回微調，觸發「沒有進展」反覆重試（目標 1 花 61 s） |
| AMCL `update_min_d` / `update_min_a` 0.25 m / 0.2 rad → 0.1 / 0.1 | 讓每次停下時的估計較新 |
| 中途取消的時間估計（假設速度 0.3 → 0.5 m/s） | 原設定太慢，第一次「取消」在取消前就到點了 |

試跑觀察（照實記錄，判準不變）：模擬速度約即時 1.0 倍；機載 depth 與真實位姿下的 ray-cast 中位誤差 0.4 mm（相機模型與 Core 一致）；
到點時 AMCL 誤差中位數 3.9 cm / 0.032 rad；**有 1 組（初始 + 一個到點視角）在物件存在時，用估計位姿算出全部 64 個位置都被看穿**
（同一組用真實位姿為 95.3%），detector 有看到消防栓所以判定仍是 `present`。這正是 C6 要檢查的風險，以正式 B0 批次判定。
