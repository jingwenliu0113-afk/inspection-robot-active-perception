# 005 — Core detector 選型協定（預先登錄）

- **日期**：2026-10-13
- **狀態**：**已凍結 `detector-v1` = torchvision Faster R-CNN MobileNetV3-Large FPN（`frcnn-mnv3`）**（2026-10-13，見附錄 B）
- **是否在看過正式結果後才新增 / 修改**：否。本協定寫於任何 detector 執行之前。

## 問題

所有方法共用同一個 detector（SPEC §5–§6、decision 004），detector 的 confidence 直接進入 shared decision rule。
使用者 2026-10-13 決定：

- 只比較 **YOLOv8m**、**YOLO11m**（Ultralytics，COCO 預訓練）與 **torchvision Faster R-CNN MobileNetV3**（`fasterrcnn_mobilenet_v3_large_fpn`，`COCO_V1` 權重）。
- 用**相同的獨立開發資料**比較準確率、遮擋表現、速度、資源需求、授權，最後固定一個模型。
- **不得使用正式測試集選型。**
- 視覺模型比較與重度 GPU 運算在 `gpu-server`（RTX 5070 Ti），遵守共享 GPU lock。

Core 不做 fine-tuning（那是 Advanced A）。

## 資料（獨立開發資料）

- namespace `detsel`（decision 006），gen-v2 world，與正式 `core` namespace 的 seed 流獨立，**不屬於 train / val / test，也不是 pilot**。
- 用與正式實驗相同的 Gazebo render 管線（decision 007）產生：每個 episode 13 個 viewpoint × 4 variants。預設 40 個 scene group（2080 張 frame，present / absent 各半）。
- 每張 frame 的 GT（只用於評估）：物件存在與否、可見部分 bbox（full pass labels）、完整 bbox（clear pass labels）、`vis_fraction`、`visibility`（decision 007 定義）。

## 推論設定（三個模型一致的原則）

- 只取 COCO **fire hydrant** 類別（以類別名稱比對，不寫死 index）。
- 低門檻輸出完整候選以畫 PR / ROC：Ultralytics `conf=0.001, max_det=100, imgsz=640`；torchvision `box_score_thresh=0.001, box_detections_per_img=100`，其餘用預設前處理。
- 不做 TTA、不改 NMS 預設值、不 fine-tune。

## 指標

| # | 指標 | 定義 |
|---|---|---|
| P | **image-level AUROC（主指標）** | 每張 frame 的 fire hydrant 最高 confidence；正例 = 物件存在且 `visibility ≥ 0.5`，負例 = 物件不存在 |
| S1 | 遮擋表現 | 在 absent frame 誤報率 = 5% 的 confidence 門檻下，`vis_fraction` 分箱 [0.25, 0.5)、[0.5, 0.75) 的 frame-level recall 平均 |
| S2 | AP50 | 以可見部分 bbox 為 GT 的 fire hydrant AP（IoU 0.5）；`vis_fraction < 0.1` 或可見面積 < 100 px 的 frame 不計入 |
| S3 | 誤報 | absent frame 在 confidence 0.3 / 0.5 的誤報率、absent frame 最高 confidence 分佈 |
| S4 | 各遮擋分箱的 recall 與平均 confidence | `vis_fraction` 分箱 [0, 0.25)、[0.25, 0.5)、[0.5, 0.75)、[0.75, 1] |
| R1 | 速度 | batch = 1、暖機後 p50 / p90 延遲：Mac CPU、Mac MPS、RTX 5070 Ti（GPU lock 下） |
| R2 | 資源 | 參數量、權重檔大小、峰值 RAM / VRAM |
| L | 授權 | 程式碼與權重授權，對公開 repo 的影響 |

## 選擇規則（預先登錄）

1. 主指標 P 最高者勝出。
2. 若有其他模型的 P 與最高值相差 ≤ 0.01，在這些模型間以 S1 較高者勝出。
3. 仍無法區分（S1 相差 ≤ 0.02）時，依序偏好：授權較寬鬆（BSD > AGPL）、Mac CPU p50 延遲較低。
4. 選定後凍結為 `detector-v1`：模型名稱、權重檔 sha256、套件版本、推論參數。之後 decision rule 的門檻在 train / val 上依此 detector 調整（decision 004 的程序）。

若勝出者為 AGPL-3.0（Ultralytics），其授權義務另記錄於選型結果附錄，並在 README 註明。
（2026-10-17 註：本 repo 以 BSD-3-Clause 公開前，已移除 YOLO 的轉接程式與 `ultralytics` 依賴；選型結果 `results/detector-selection/` 保留未改，但 YOLO 的偵測無法再從本 repo 重跑。本段保留當時的紀錄。）

## 執行地點

- 準確率指標（P、S1–S4）與裝置無關，在可取得的機器上跑：`gpu-server`（GPU lock）優先；若 `gpu-server` 不可用，改在 Mac 執行（小型推論，MACHINE_POLICY 允許），並在結果附錄記錄硬體。
- R1 的 GPU 延遲只能在 `gpu-server` 量；不可用時標記 deferred，不影響選擇規則（規則不使用 GPU 延遲）。

## 被凍結的項目

候選模型清單、資料來源與 namespace、推論設定、指標定義、選擇規則。

## 附錄 A（2026-10-13，任何 detector 執行之前）：推論設定的實作細節

- torchvision 的 `box_detections_per_img` 是**所有類別合計**的上限，低門檻時 fire hydrant 的框可能被其他類別擠掉；
  Ultralytics 的 `classes=[fire hydrant]` 則是先過濾類別再取 `max_det`。為了讓兩者都得到「最多 100 個 fire hydrant 候選」，
  torchvision 改設 `box_detections_per_img=1000`，輸出後只保留 fire hydrant、依 confidence 取前 100。
- Ultralytics 對 numpy 輸入視為 **BGR**；frame store 的 RGB 影像在送進 Ultralytics 前轉成 BGR。torchvision 吃 RGB float [0, 1]。
- Ultralytics 以環境變數 `YOLO_OFFLINE=1` 執行（不連網、不送使用統計），不修改使用者層級設定檔。
- 權重檔手動下載到 `models/`（不進 git），sha256 記錄在選型結果附錄：
  - `yolov8m.pt`、`yolo11m.pt`：`https://github.com/ultralytics/assets/releases/download/v8.4.0/`
  - `fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth`：`https://download.pytorch.org/models/`（torchvision `COCO_V1`）

## 附錄 B（2026-10-13）：選型結果與凍結 `detector-v1`

### 執行

- 資料：`data/episodes/gazebo-detsel.json`（split = `detsel`，40 scene groups、160 episodes、2080 張 frame；present 1040 / absent 1040），frame store `renders/detsel`（image `sha256:49d6e69b…`）。
- 準確率與 GPU 延遲：`gpu-server` RTX 5070 Ti，torch 2.13.0+cu130、torchvision 0.28.0、ultralytics 8.4.176，在 `/tmp/ai-portfolio-gpu.lock`（`flock -n`）下執行，lock 檢查時為空閒。
- Mac 延遲：M4 Pro，torch 2.14.1、torchvision 0.29.1（`--bench-only`）。
- 原始輸出：`results/detector-selection/selection.json`；表格：`results/detector-selection/table.md`。
- 權重 sha256（皆與官方來源一致；YOLO 以 GitHub release asset digest 核對）：
  - `yolov8m.pt` `5d4a90cdc7a21786cc59cd19778e9eafff836df9e2da32524737c7ee6efe4fe5`
  - `yolo11m.pt` `d5ffc1a674953a08e11a8d21e022781b1b23a19b730afc309290bd9fb5305b95`
  - `fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth` `fb6a3cc702b1df54c18a44b26708cd083614211062d0c36d2ca7bf9270df3533`

### 結果

| 指標 | yolov8m | yolo11m | frcnn-mnv3 |
|---|---|---|---|
| **P** image AUROC [95% CI] | 1.0000 [1.000, 1.000] | 1.0000 [1.000, 1.000] | 1.0000 [1.000, 1.000] |
| **S1** 遮擋 recall @ FPR 5% [95% CI] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] |
| S1 使用的門檻 τ（absent FPR 5%） | 0.0000 | 0.0000 | 0.0031 |
| **S2** AP50（可見部分 bbox） | 0.995 | 0.995 | 0.996 |
| **S3** absent 誤報率 @0.3 / @0.5 | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 |
| S3 absent 最高 conf（p99 / max） | 0.000 / 0.000 | 0.000 / 0.000 | 0.013 / 0.023 |
| **S4** vis_fraction [0.0, 0.25)（n=176）recall@0.5 / 平均 conf | 0.074 / 0.071 | 0.057 / 0.052 | 0.006 / 0.019 |
| **S4** vis_fraction [0.25, 0.5)（n=24）recall@0.5 / 平均 conf | 1.000 / 0.927 | 1.000 / 0.899 | 0.625 / 0.554 |
| **S4** vis_fraction [0.5, 0.75)（n=16）recall@0.5 / 平均 conf | 1.000 / 0.957 | 1.000 / 0.938 | 0.875 / 0.863 |
| **S4** vis_fraction [0.75, 1.0]（n=824）recall@0.5 / 平均 conf | 1.000 / 0.971 | 1.000 / 0.955 | 1.000 / 0.990 |
| **R1** p50 / p90 延遲 ms，RTX 5070 Ti（CUDA） | 6.6 / 7.1 | 7.4 / 7.8 | 8.7 / 9.5 |
| **R1** p50 / p90 延遲 ms，Mac M4 Pro MPS | 19.6 / 20.5 | 21.6 / 22.5 | 26.3 / 28.3 |
| **R1** p50 / p90 延遲 ms，Mac M4 Pro CPU | 49.3 / 49.5 | 52.5 / 52.7 | 144.0 / 146.2 |
| **R2** 參數量 | 25.9 M | 20.1 M | 19.4 M |
| R2 峰值 VRAM（CUDA，batch 1） | 145 MB | 169 MB | 242 MB |
| R2 權重檔大小 | 52.1 MB | 40.7 MB | 77.8 MB |
| **L** 授權 | AGPL-3.0 | AGPL-3.0 | BSD-3-Clause |


### 依預先登錄規則的判定

1. P：三者都是 1.0000（差距 0 ≤ 0.01）→ 三者進入下一步。
2. S1：三者都是 1.000（差距 0 ≤ 0.02）→ 三者進入下一步。
3. 授權：BSD-3-Clause 優先於 AGPL-3.0 → **`frcnn-mnv3` 勝出**。

### 必須一併記錄的限制（不改變判定）

- **主指標與 S1 在這個 world 飽和**：absent frame 幾乎沒有 fire hydrant 候選（YOLO 在 conf 0.001 下為 0；FRCNN 最高 0.023），
  5% 誤報率門檻因此趨近 0，S1 只要「有任何偵測」就算命中。三個模型在「物件看得到時能否分辨有無」上沒有差別；
  這表示在本 world，**可見時的 perception 不是瓶頸，遮擋（viewpoint）才是**，正符合 Core 要隔離的研究變因。
- **部分遮擋時的 confidence 行為不同**（S4，資訊性）：YOLO 在 vis_fraction 0.25–0.75 仍給 0.90–0.96；
  FRCNN 隨遮擋下降（0.55 / 0.86），在 0.5 門檻下 [0.25, 0.5) 的 recall 為 0.625。shared decision rule 的 τ_present 之後會在 train / val 上依 FRCNN 調整（decision 004 程序）。
  FRCNN 的 confidence 與可見程度較相關，也讓 rule-NBV 的「弱偵測吸引」特徵有訊號可用；這是觀察，不是選型理由。
- **速度**：YOLO 較快（CUDA 6.6 vs 8.7 ms；Mac CPU 49 vs 144 ms）。Core 採 render-then-replay，每張 frame 只推論一次，延遲不影響實驗。
- 部分遮擋分箱樣本少（24 + 16 張），因為方柱多半完全擋住或完全沒擋到。

### 跨裝置一致性

同一批 104 張 frame，FRCNN 在 Mac CPU / MPS 與 CUDA 的每張最高 confidence 差距：中位數 2.1e-5、最大 5.3e-4。
正式 detection 快取統一在 CUDA 產生；ROS 2 線上 node 在 Mac 推論時只有極小差異（pilot 的線上 / replay 一致性檢查會量化）。

### 凍結：`detector-v1`

| 項目 | 值 |
|---|---|
| 模型 | torchvision `fasterrcnn_mobilenet_v3_large_fpn`，`COCO_V1` 權重 |
| 權重 sha256 | `fb6a3cc702b1df54c18a44b26708cd083614211062d0c36d2ca7bf9270df3533` |
| 目標類別 | COCO `fire hydrant`（torchvision index 11，以名稱比對） |
| 推論參數 | `box_score_thresh=0.001`、`box_detections_per_img=1000` → 保留前 100 個 fire hydrant；預設前處理（min_size 800） |
| 正式快取產生環境 | `gpu-server` RTX 5070 Ti，torch 2.13.0+cu130 / torchvision 0.28.0，GPU lock 下 |

之後若要換 detector，只能以新版本（`detector-v2`）另開 decision log，並在新一輪 test 報告，保留舊結果。
