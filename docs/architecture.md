# 系統架構

本專案有兩條執行路徑，共用同一套判定程式碼：

- **Core（teleport）**：相機直接放到候選視角拍攝，排除導航的影響，只比較「選哪個視角」。
- **Advanced B（Nav2）**：TurtleBot 4 用 Nav2 實際開到視角。判定只能用機器人自己估計的位姿與機載感測器。

兩條路徑都**只在 Gazebo 模擬中執行**。實機的情況見 [README「驗證範圍」](../README.md#驗證範圍模擬已驗證--實機未驗證)。

## 1. 資訊邊界：判定能讀什麼、評分才能讀什麼

| 資料 | 判定（可部署） | Oracle（上限，不可部署） | 評分 / 分析 |
|---|---|---|---|
| RGB、depth（相機） | ✓ | ✓ | ✓ |
| detector-v1 輸出 | ✓ | ✓ | ✓ |
| 候選視角（只由 inspection zone 與場景 seed 決定） | ✓ | ✓ | ✓ |
| 設施地圖（牆、柱子；**不含目標物**） | ✓（只有 B） | ✓ | ✓ |
| AMCL 估計位姿 → depth 精修（只有 B） | ✓ | — | ✓ |
| 定位器回報的位姿共變異數（v3 的先驗閘門） | ✓ | — | ✓ |
| zone 位置（v3 以 depth 定位偵測框，判斷是否在 zone 內） | ✓ | ✓ | ✓ |
| 模擬器真實位姿 `/gt/odom` | ✗ | ✗ | ✓ |
| 物件是否存在、位置、每個視角的可見度標籤 | ✗ | ✓ | ✓ |

四個方法（Single、Random、Rule-NBV、Oracle）共用同一條判定規則，差別只在選了哪些視角。
程式上的保護包括：leakage tests（候選視角與物件無關）、`seal.py`（封存資料只能 `--reproduce`）、`tune.py`（拒絕 test / holdout）。

## 2. Core：render-then-replay

```mermaid
flowchart TB
  subgraph DATA["資料（seeded、版本化）"]
    GEN["場景產生器 gen-v2<br/>柱子遮擋、消防栓有 / 無"] --> SPEC["episode specs<br/>train / val / test / holdout"]
  end
  subgraph SIM["Gazebo Harmonic（Docker、headless）"]
    REN["teleport render<br/>每集 13 個視角<br/>RGB / depth / labels"]
  end
  SPEC --> REN --> FS["frame store（npz）"]
  FS --> DET["detector-v1<br/>FRCNN-MobileNetV3"] --> DC["detection cache"]
  subgraph LOOP["判定迴圈（四個方法相同）"]
    H["harness<br/>budget 1–5"] -->|已拍攝的觀測| POL["policy<br/>Single / Random / Rule-NBV / Oracle"]
    POL -->|下一個視角| H
    H --> DR["共用 decision rule<br/>decision-v1 / decision-v2"]
  end
  FS --> H
  DC --> H
  H --> GR["grader（只有這裡讀 GT）"] --> MET["metrics + scene-group bootstrap"] --> RES["results/ + SEALED.sha256"]
```

- 每個視角只 render 一次，四個方法 replay 同一份觀測，所以方法之間的差異只來自選視角（[decision 007](decisions/007-gazebo-observation-pipeline.md)）。
- ROS 2 線上版（`ros_ws/src/inspection_ap_ros` 的 inspector node）透過 `ros_gz_bridge` teleport，即時跑 detector 與 policy；
  pilot 上與 replay 的視角序列、判定 192 / 192 相同（v2：168 / 168）。

### 判定規則（`decision-v2`，四個方法共用）

- **present**：任一視角的消防栓 confidence ≥ 0.7。
- **absent**：inspection zone 內 64 個「物件可能站的位置」，每一個都在某個視角的 depth 中被**看穿**（視線沒被擋），而且所有 confidence < 0.02（decision 012 凍結值）。
  物件真正站的位置不可能被看穿（depth 先打到物件），所以 detector 漏看也不會變成 false absent。
- 其餘都是 **inconclusive**。

### 選視角（`rule-nbv-v2`）

用已拍攝的 depth 建出「已知障礙 / 已知空 / 未知」地圖，預測每個候選視角能看穿多少尚未看穿的位置；經過未知區域的視線只給一半信任。
已知限制：初始視角被完全擋住時，地圖幾乎全是未知，候選常常同分，由候選編號決定（[failure analysis §5](failure-analysis.md)；Demo 中可以看到）。

## 3. Advanced B：Nav2 閉迴路

```mermaid
flowchart TD
  START["起點拍攝<br/>桅桿相機 RGB-D"] --> DET["detector-v1"]
  DET --> OBS["decision-016 觀測<br/>depth 對設施地圖精修位姿<br/>看穿判定取位姿餘裕"]
  OBS --> DEC{"decision-v2"}
  DEC -->|"present / absent<br/>或 budget 用完"| OUT["回報判定"]
  DEC -->|inconclusive| POL["rule-nbv-v2<br/>選下一個候選視角"]
  POL --> NAV["Nav2 NavigateToPose<br/>AMCL 定位、MPPI 控制"]
  NAV --> REL["停點重定位<br/>精修位姿 → /initialpose<br/>超出容忍值就重送目標，最多 2 次"]
  REL --> CAP["拍攝"] --> DET
  GT["/gt/odom、物件標籤"] -.->|只用於評分| SCORE["b1_analysis / failure_analysis"]
```

| 元件 | 內容 |
|---|---|
| 機器人 | TurtleBot 4（`nav2_minimal_tb4_sim`），移除 OAK-D，加 1.1 m 桅桿相機（俯角 18°，內參同 Core 640×480、hfov 60°） |
| 定位 / 導航 | AMCL（TB4 雷射）＋ Nav2 1.3.13、MPPI；到點容忍 0.07 m / 0.05 rad |
| 地圖 | 由場景幾何產生：8 m 圍牆＋柱子＋zone 禁行區；**不含目標物**，present / absent 兩個變體共用同一張地圖 |
| `nav-pose-v1` | 把 depth 中 0.15–0.85 m 高的障礙點對齊牆內側面與柱子輪廓（2D、coarse-to-fine），退化時放棄 |
| `nav-margin-v1` | 對 27 個鄰近位姿取「最少看穿」的結果；精修失敗時改用較寬的餘裕 |
| `nav-relocalize-v1` | 到點後精修 → 發布 `/initialpose` → 仍超出容忍值就重送目標（最多 2 次） |
| 批次執行 | 每個（episode, 方法, seed）一個 `inspection-ap-navdet` 容器；動態工作佇列（`mkdir` 取號）、可續跑、Nav2 啟動看門狗 180 s |

設計來源：[decision 015](decisions/015-advanced-b-start-and-b0-protocol.md)（B0 協定）→ [016](decisions/016-b0-pose-refinement-and-margin.md)（B0 失敗後的修正）→
[017](decisions/017-b1-closed-loop-protocol.md)（閉迴路）→ [018](decisions/018-b2-formal-evaluation-protocol.md)（正式評估，預先登錄）→ [019](decisions/019-b2-result-and-advanced-b-closure.md)（結果）。

## 3a. v3–v5：模擬誤差下的可靠性管線（目前的正式版本是 v5）

Core 的 render 影像不變，`V3World`（`activeperception/v3/eval.py`）在 replay 時加上 depth / 位姿誤差，再走 v3–v5 的判定。
誤差以（episode、視角、等級）固定 seed 抽樣，所以同一管線重跑會逐項相同；四個方法仍共用同一條判定規則。

```mermaid
flowchart LR
  R["render 的 RGB-D<br/>（與 Core 同一份）"] --> N["誤差模型<br/>depth D1–D3、位姿 L1–L2<br/>固定 seed"]
  N --> P["位姿精修 nav-pose-v4<br/>4σ 搜尋、比例假設 0.96–1.04<br/>先驗閘門 3σ"]
  P -->|成功| M1["精修位姿<br/>餘裕 6 cm ＋ 假設離散度"]
  P -->|退化| M2["定位器位姿<br/>餘裕 max(10 cm, 3σ)"]
  P -->|與定位器矛盾| BL["不提供看穿"]
  M1 --> S["see-v5<br/>27 個位姿的穩健看穿<br/>缺值被包住時不否決"]
  M2 --> S
  N --> G["decision-v4<br/>±8% depth 區間的 zone 過濾"]
  S --> D{"decision-v2 門檻<br/>present / absent / inconclusive"}
  BL --> D
  G --> D
```

- 「與定位器矛盾 → 不提供看穿」是防範過度自信定位器的保護；它也是 D3×P0 absent 較難判的原因。
  放寬它的研究假設 H-P 未通過安全 Gate（[decision 037](decisions/037-d3p0-diagnosis-and-proposal.md)、[hp-development](hp-development.md)），不屬於任何正式管線。
- 凍結設定：`activeperception/v5/frozen_v5.py`（= `v4/frozen_v4.py` ＋ see-v5）。

## 4. 程式模組

| 位置 | 角色 |
|---|---|
| `activeperception/episodes.py`、`types.py` | 場景與 episode 定義、split、GT 標記 |
| `activeperception/sim/` | Gazebo client、teleport render、replay world、解析 ray-cast（檢查 depth） |
| `activeperception/sensing.py` | depth → zone 可見度、障礙高度圖、64 個位置的看穿判定 |
| `activeperception/decision.py` | `decision-v1` / `decision-v2`（四個方法共用） |
| `activeperception/policies/` | Single、Random、Rule-NBV v1 / v2、Oracle v1 / v2 |
| `activeperception/harness.py`、`grader.py`、`metrics.py` | budget 迴圈、評分（唯一讀 GT 的地方）、指標與 bootstrap |
| `activeperception/detector/` | 三個候選 detector、選型評估、權重 sha256 驗證、偵測快取 |
| `activeperception/tune.py`、`experiment*.py`、`frozen*.py` | 預先登錄的調參、正式 runner、凍結設定 |
| `activeperception/seal.py`、`SEALED.sha256` | 封存已用過的正式資料與結果 |
| `activeperception/failure_analysis.py` | Core 失敗分析（只讀已 commit 的結果） |
| `activeperception/nav/` | Advanced B：場景 / 地圖、TB4 桅桿相機、位姿精修與餘裕、B0 / B1 driver、分析、失敗分析 |
| `activeperception/r0a.py`、`r0b*.py` | R0：真實照片上的 detector、模擬的 depth / 位姿誤差 |
| `activeperception/v3/` | v3：`decision-v3`（zone 過濾）、`see-through-v3`、`nav-pose-v3`（先驗閘門、矛盾時不可信）、開發評估、凍結設定、正式 runner |
| `activeperception/v4/` | v4：`nav-pose-v4`（4σ 搜尋、比例假設 ＋ 尺度雅可比、依離散度加大的餘裕）、`decision-v4`（depth 區間 zone 過濾）、凍結設定、正式 runner |
| `activeperception/v5/` | v5：`see-v5`（缺值位姿被看穿位姿包住時不否決）、比例自我校正（開發，未採用）、開發 / 正式 runner、Mac heavy lock 檢查 |
| `activeperception/inzone/` | E0（decision 036）：zone 內相似物件的指標、可行性檢查、E1 資料規格與檢查工具、確認式 present（預設關閉） |
| `activeperception/d3p0/` | D3×P0 診斷（decision 037）：凍結 v5 的逐視角 / 逐位置歸因（真實位姿只用於歸因） |
| `activeperception/v6/` | H-P（decision 037，**未通過安全 Gate**，`hp_c` 預設 0 = 關閉）：成本比、開發設定、開發 runner 與報告 |
| `activeperception/preflight.py` | 重工作前的資源預檢：Mac heavy lock、CPU 負載、RAM、Apple GPU |
| `activeperception/detv2/` | A：detector-v2 的資料、訓練（RTX）、評測、正式 runner |
| `activeperception/depthnoise/` | B：真實 depth 誤差統計、公開資料下載、D3 修正模型 |
| `ros_ws/src/inspection_ap_ros/` | ROS 2 inspector node（Core 線上版） |
| `docker/` | 映像（sim / ros / nav / navdet）、render、smoke、Nav2 批次、Demo |
| `tools/` | 圖表（`make_figures.py`）、Demo 動畫（`make_demo.py`） |

## 5. 執行環境

| 映像 | 內容 | 用途 |
|---|---|---|
| `inspection-ap-sim` | ROS 2 Jazzy + Gazebo Harmonic（arm64，headless ogre2 / llvmpipe） | teleport render |
| `inspection-ap-ros` | + `ros_gz_bridge` 與 inspector node | Core ROS 2 線上執行 |
| `inspection-ap-nav` | + Nav2 1.3.13、TurtleBot 4 模擬（apt 0 upgraded，不改動底層） | B0 |
| `inspection-ap-navdet` | + CPU torch / torchvision（detector 在容器內推論） | B1 / B2、Demo |

- 主要機器：Apple M4 Pro（48 GB）上的 Docker Desktop。detector 選型與 Core 的偵測在共享 GPU 機器上執行，遵守 `/tmp/ai-portfolio-gpu.lock`（[MACHINE_POLICY.md](../MACHINE_POLICY.md)）。
- 只使用 `inspection-ap-*` 名稱的映像與容器，不碰其他專案的容器、網路與 volume。
- 版本紀錄：[docs/platform/versions.md](platform/versions.md)、[versions-nav.md](platform/versions-nav.md)。
