# Advanced B（Nav2）：可行性評估與方案（待使用者決定）

- **日期**：2026-10-13
- **狀態**：**提案，未啟動**。依使用者指示（decision 014）只做評估，不建置映像、不寫 Nav2 程式、不產生資料。
- 本次只做了唯讀檢查：在一次性容器（`--rm`，未保存）中查詢套件可用性與安裝大小；沒有修改主機或既有映像。

## 結論

**可行，而且整個 B 可以在 Mac 上完成，不需要 GPU、也不需要採購。** 需要釐清的風險有兩個，都能在約 1 天的 spike（B0）內得到答案：

1. **CPU 軟體渲染下的模擬速度**：Nav2 需要連續的物理與感測器模擬，現在的 render-then-replay 不能直接沿用。
2. **定位誤差與 v2 安全性**：`decision-v2` 的看穿容忍值是 3 cm；改用機器人自己估計的位姿（AMCL）之後，false absent = 0 是否仍成立，是 B 最有價值的研究問題。

建議依序決定：**先核准 B0 spike（go / no-go）**，看結果再決定是否做 B1–B2。

## 1. B 要回答的問題

SPEC Advanced B：把 teleport 換成實際導航，新增 path success、navigation latency、collision / timeout、reachable viewpoint rate，
並**保留 teleport 結果**，用來區分導航失敗與 active perception 失敗。具體問題：

| | 問題 | 為什麼對實際巡檢重要 |
|---|---|---|
| Q1 安全 | 用 Nav2 與估計位姿時，v2 是否仍然 false absent = 0？ | 實機最怕「漏看卻回報沒有」 |
| Q2 準確率損失 | teleport → Nav2 掉多少 accuracy？拆成到不了、位姿誤差、超時 | 知道瓶頸在導航還是感知 |
| Q3 成本 | 各方法的行走距離與時間（Rule vs Random vs Oracle） | 巡檢機器人的實際代價 |

方法沿用凍結的 v2（`decision-v2` + `rule-nbv-v2`），四個方法共用同一條判定規則；**不重新調整策略參數**，只調 Nav2 本身的整合參數（只用開發資料）。

## 2. 已確認的事實

| 項目 | 結果 |
|---|---|
| Nav2（Jazzy，arm64 binary） | `navigation2` 1.3.13、`nav2_bringup` 1.3.13 可直接 apt 安裝 |
| Gazebo Harmonic 用的機器人模擬 | `nav2_minimal_tb4_sim` / `tb3_sim` 1.0.1、`turtlebot4_simulator` 2.0.2、`turtlebot3_gazebo` 2.3.7 |
| 其他可用套件 | `slam_toolbox` 2.8.5、`depthimage_to_laserscan` 2.5.1、`robot_localization` 3.8.3 |
| 安裝在現有映像上 | 336 個套件，下載約 184 MB，安裝後多約 **1.08 GB** |
| 現有 teleport 管線 | 每個視角約 0.30 s（10 Hz 感測器、RTF 1，`docs/platform/m2-smoke.md`） |
| GPU | 不需要；detector 在容器 CPU 上與 CUDA 的 confidence 差 ≤ 0.004（既有驗證） |

## 3. 與 Core 的差異（B 必須處理的設計問題）

1. **相機高度**：現在的視角高 0.9–1.3 m、往下 12–24°；一般地面機器人的相機只有約 0.3 m 高。
   → 在機器人上加約 1.1 m 的桅桿相機（模擬與實機都做得到），新資料固定相機高度與俯角。
2. **機器人站不進現在的場景**：柱子邊緣到相機環只保證 ≥ 0.15 m，TurtleBot 4 半徑約 0.17 m，再加上避障膨脹就會卡住。
   → 新的場景生成器（例如 `gen-nav-v1`）加大間隙。
3. **不能再 replay**：機器人實際停下的位姿每次都不同，預先 render 的觀測不適用。
   → 「導航到點 → 在**實際停下的位姿** render 觀測」；同一批 episodes 另跑 teleport 作為對照。
4. **位姿來源**：判定規則與策略必須使用機器人**估計**的位姿；GT 位姿只用於評分。這直接測試 Q1。
5. **地圖不得洩漏答案**：Nav2 用的佔據地圖由場景幾何產生，只含柱子，**不含消防栓**；present / absent 兩個 variant 共用同一張地圖。策略不讀地圖。
6. **導航失敗的規則需預先登錄**：例如導航失敗或超時仍然消耗 budget，並在停下的位置拍攝。
7. **新資料**：`core` 與 `holdout` 已封存（decision 014），B 必須在新的 decision log 之後以新 namespace 產生資料；開發子集調 Nav2 參數，正式子集只跑一次。

## 4. 工作範圍（三個階段，每個階段結束都可以停）

| 階段 | 內容 | 產出 | 估計 |
|---|---|---|---|
| **B0 spike** | 建 Nav2 映像；TurtleBot 4 加桅桿相機；在類似場景中導航到 12 個環上視角；量模擬速度（RTF）、到點成功率、到點誤差 | go / no-go 報告（不是研究結果） | 約 1 天 |
| **B1 整合** | decision 015（協定預先登錄）、新場景生成器與地圖、「導航後拍攝」harness、inspector node 改用 `NavigateToPose`、新指標、tests、開發資料試跑 | 可重現的 Nav2 管線 | 約 3–5 天 |
| **B2 正式評估** | 新 namespace 正式資料（例如 50–100 scene groups），teleport 與 Nav2 在同一批 episodes 各跑一次 | Q1–Q3 結果、README 段落 | 約 1–2 天（主要是運算） |

B0 的 go / no-go 判準（建議）：Nav2 運作時 RTF ≥ 0.5；可到達的視角導航成功率 ≥ 90%；到點位置與朝向誤差可量測且穩定。未達標就停在 B0，記錄原因。

運算時間粗估（B0 前無法確定）：每次 episode 執行（最多 2 次移動）約 1–2 分鐘牆鐘時間；200 episodes × 7 次執行（Random 5 seeds、Rule、Oracle）
約 **10–40 小時機器時間**，可分批、可續跑。

**不在範圍內**：SLAM 研究、RL、多機器人、實體機器人、路徑最佳化研究。

## 5. 環境需求

| 項目 | 需求 | 需要你核准？ |
|---|---|---|
| Mac Docker 新映像 | 以現有 `inspection-ap-sim` 為底加裝 Nav2（約 +1.1 GB 磁碟）；主機系統不變 | **是**（新增安裝） |
| 機器人模型 | TurtleBot 4（`nav2_minimal_tb4_sim`）＋ 本 repo 內的桅桿相機設定 | 是（平台選擇） |
| gpu-server | 不需要。它的 Ubuntu-22.04 不支援 Jazzy，也不得改動 | 否 |
| 其他專案 | 不碰其他容器 / 網路 / volume；`rtu-maintenance-platform` 每小時關閉 Docker Desktop 的問題仍在，B 的執行必須能續跑 | 否 |
| 付費 / 帳號 | 不需要 | 否 |

## 6. 往實際機器人巡檢的路徑（SPEC 列為 Optional，需另外決定）

B 完成後，同一套 ROS 2 程式（Nav2 + inspector node）可以直接搬到實機。實機另外需要：

- **硬體採購（付費決策）**：例如 TurtleBot 4。2022 年上市價 Standard US$1,850、Lite US$1,195，目前價格更高（例如有通路的開箱品約 US$2,575），實際價格需詢價。
  另外還需要桅桿與相機支架、實體目標物（或替代物）、可建圖的測試場地。
- **感知的 sim-to-real 差距**：`detector-v1` 只在 Gazebo 影像上驗證過；實際影像很可能需要 Advanced A（以實拍資料微調 detector）。
- 實機評估同樣要預先登錄協定、使用新資料，並與 B 的模擬結果分開報告。

## 7. 請你決定

1. **方案**（擇一）：
   - **方案 1（建議）**：B0 → 達標後 B1 → B2，完整回答 Q1–Q3，約 1–1.5 週工作量，不需採購。
   - **方案 2（精簡）**：只做 B0 加一個小型線上展示（Nav2 實際走到視角並完成判定），不做正式評估、不宣稱研究結果，約 2–3 天。
   - **方案 3**：維持現狀，Core 到此結束。
2. 是否核准在 Mac 上建 Nav2 的 Docker 映像（約 +1.1 GB）。
3. 模擬機器人平台：TurtleBot 4（建議，與可採購的實機一致）或 TurtleBot 3。
4. 主要設定：凍結的 v2（建議）；v1 是否也一併在 Nav2 上評估。

Sources: [TurtleBot 4 launch (Robotics 24/7)](https://www.robotics247.com/article/clearpath_robotics_open_robotics_launch_turtlebot_4_ros_2_support/irobot)、
[RobotShop listing](https://www.robotshop.com/products/clearpath-robotics-turtlebot-4-mobile-robot-open-box)；套件版本來自 2026-10-13 在 Jazzy arm64 容器中的 `apt-cache policy`。
