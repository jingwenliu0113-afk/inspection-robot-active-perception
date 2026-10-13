# Inspection Robot + Active Perception

> **狀態（2026-10-13）：Core v1 完成，正式 test 已跑完一次，Gate 已判定（[decision 010](docs/decisions/010-core-test-result-and-gate.md)）。**
> Rule-based NBV 在固定 viewpoint budget 下穩定勝過 Single View 與 Random，且已接近 Oracle 上限 → 依 SPEC 不進 RL。
> 正式數字只來自 ROS 2 Jazzy + Gazebo Harmonic 的 `core` test split；synthetic world 只用於 correctness tests。

## 一句話問題

在物件可能「可見、被遮擋、根本不存在」的 inspection task 中，active perception 能不能在固定觀測預算下，
比單一視角與隨機移動更可靠地判斷 `present / absent / inconclusive`？

完整研究定義見 [SPEC.md](SPEC.md)，實驗規範見 [docs/EXPERIMENT_RULES.md](docs/EXPERIMENT_RULES.md)，
所有會影響結論的設計決策（全部在看結果前寫成）見 [docs/decisions/](docs/decisions/)。

![三種 GT 狀態](docs/figures/three_states.png)

巡檢目標是 Gazebo Fuel 的消防栓（COCO `fire hydrant`），放在半徑 0.5 m 的 inspection zone 裡；1–3 根方柱可能擋住視線。
「沒偵測到」不等於 `absent`：單一視角時，被擋住的消防栓與根本沒有消防栓幾乎無法分辨（pilot AUROC 0.75）。

## 結果（`core` test split：131 scene groups、524 episodes）

Accuracy（3 類），95% CI 為以 scene group 為 cluster 的 bootstrap（1000 次）；Random NBV 為 5 個 run seeds 平均。

| budget | Single View | Random NBV | **Rule-based NBV v1** | Oracle NBV（上限） |
|---|---|---|---|---|
| 1 | 0.202 [0.16, 0.25] | 0.202 | 0.202 | 0.202 |
| 2 | 0.202 | 0.620 [0.58, 0.66] | **0.706 [0.66, 0.75]** | 0.710 [0.67, 0.75] |
| 3 | 0.202 | 0.907 [0.89, 0.92] | **0.996 [0.99, 1.00]** | 1.000 |
| 5 | 0.202 | 0.998 [0.996, 1.000] | **1.000** | 1.000 |

| 成對差異（同一批 episodes） | budget 2 | budget 3 |
|---|---|---|
| Rule − Random，accuracy | **+0.086 [0.072, 0.101]** | **+0.089 [0.069, 0.108]** |
| Rule − Random，inconclusive rate | −0.085 [−0.100, −0.071] | −0.088 [−0.107, −0.068] |
| Rule − Single，accuracy | +0.504 [0.49, 0.52] | +0.794 [0.75, 0.83] |
| Oracle − Rule，accuracy | +0.004 [0.000, 0.011] | +0.004 [0.000, 0.011] |

![accuracy vs viewpoint budget](docs/figures/accuracy_vs_budget.png)

- **Single View 從不給出錯誤的肯定答案，但 80% 的時候只能說「不知道」**：所有方法共用的 decision rule 不會把「沒看到」當成 `absent`，
  所以單一視角在 unobservable 與 absent episodes 一律 `inconclusive`（false-absent = 0）。
- **主動換視角把 inconclusive 變成正確答案**：Rule-based NBV 用已走訪視角的 depth 建出 zone 外障礙物高度圖，
  預測每個候選視角能看到多少 inspection zone；budget 3 時 accuracy 0.996（Random 0.907），平均只用 2.09 個視角。
- **已接近上限**：Oracle（讀 simulator GT）只多 0.004。依 SPEC 的 Gate，**不需要 RL**。

### False-absent 分析

| | Single | Random | Rule | Oracle |
|---|---|---|---|---|
| false-absent rate（budget 2 / 3 / 5） | 0 / 0 / 0 | 0.0015 / 0.0015 / 0.0015 | **0 / 0 / 0** | 0 / 0 / 0 |
| false-present rate | 0 | 0 | 0 | 0 |

Random 的 false absent 只發生在 `core-g0103-v0`（seeds 3、4）：隨機挑到兩個「zone 大致看得到、但消防栓剛好被柱子擋住」的視角。
Rule-based NBV 與 Oracle 在 test 上沒有任何 false absent。

### 分層（budget 2 / 3）

| GT 狀態（n） | Single | Random | Rule | Oracle |
|---|---|---|---|---|
| visible（105） | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| unobservable（157） | 0.006 / 0.006 | 0.851 / 0.978 | **0.987 / 1.000** | 1.00 / 1.00 |
| absent（262） | 0 / 0 | 0.329 / 0.827 | **0.420 / 0.992** | 0.420 / 1.000 |

budget 2 的 absent 上限是 0.420：若初始視角的 zone 被擋，兩個視角湊不到 decision rule 要求的兩個有效扇區，Oracle 也一樣。

### 殘餘失敗（可重現）

![殘餘失敗案例](docs/figures/failure_case.png)

Rule-based NBV 在 budget 2 / 3 共 156 件未答對：152 件是上述 budget 結構限制；
真正的策略失敗只有 4 件，全在 scene group `core-g0298`——初始視角看不到藏在前一根柱子後面的第二根柱子，
高度圖把未觀測區域當成空的，選到被擋的視角。細節見 [decision 010](docs/decisions/010-core-test-result-and-gate.md)。

### Detector（`detector-v1`）

在獨立的 `detsel` 資料（不是 train / val / test）比較 YOLOv8m、YOLO11m、torchvision Faster R-CNN MobileNetV3：
三者 presence AUROC 都是 1.000、AP50 0.995–0.996，預先登錄的規則因此由授權（BSD vs AGPL）決定 → **FRCNN-MobileNetV3**
（[decision 005](docs/decisions/005-detector-selection-protocol.md)、[`results/detector-selection/`](results/detector-selection/)）。
test frame 上，可見消防栓像素 ≥ 10k 時偵測率 99.8%；< 5k 時幾乎偵測不到——**瓶頸是視角，不是 detector**。

## 方法

| Policy | 可用資訊 | 角色 |
|---|---|---|
| Single View | 初始視角 | baseline |
| Random NBV | 候選集合、seed | baseline |
| Rule-based NBV v1 | depth 推得的障礙物高度圖（預測候選視角的 zone 可見度）＋ 與已訪視角的角距 | 受測方法 |
| Oracle NBV | simulator ground truth | upper bound，不可部署 |

- 四個方法共用同一條 decision rule（`decision-v1`）與同一個 detector，差別只在「選了哪些 viewpoint」。
- `absent` 需要至少 2 個方位扇區（共 8 個）有「zone 至少 30% 未被擋」的視角，且所有視角的消防栓 confidence 都 < 0.05；
  `present` 需要 confidence ≥ 0.7；其餘一律 `inconclusive`。
- 候選 viewpoint（12 個，環繞 zone）只由 inspection zone 與 scene-group seed 決定，與物件、遮擋無關（leakage tests）。
- 參數只在 train 上依預先登錄的協定調整、val 只做檢查、test 只跑一次（[decision 008](docs/decisions/008-core-set-tuning-protocol-rule-nbv-v1.md) / [009](docs/decisions/009-freeze-v1-and-test-protocol.md)）。

## 系統：ROS 2 + Gazebo

```
Gazebo Harmonic (headless, ogre2/llvmpipe)  ── ros_gz_bridge ──>  /inspector/rgb, /inspector/depth
        ^                                                                    |
        └── /world/inspection/set_pose (ros_gz_interfaces/SetEntityPose) <── inspector node
                                            (detector-v1 + decision rule + NBV policy, 同一套程式碼)
```

- **正式指標**：每個 episode 的 13 個視角在 Gazebo 各 render 一次（RGB / depth / semantic labels）→ 四個方法 replay 同一份觀測，保證候選觀測逐位元相同（[decision 007](docs/decisions/007-gazebo-observation-pipeline.md)）。
- **ROS 2 線上執行**：`ros_ws/src/inspection_ap_ros` 的 inspector node 經 `ros_gz_bridge` teleport、即時跑 detector 與 policy；
  pilot 上 192 次線上執行與 replay 的視角序列、決策 **192 / 192 相同**（[`results/pilot/`](results/pilot/)）。
- Pilot（SPEC §9）全部通過：三狀態可分、teleport 決定性（獨立重 render 逐像素相同）、timestamp、depth vs 解析 ray-cast（中位誤差 0.25 mm）、四方法同候選集、grader 不吃 inconclusive。

## 重現

```bash
uv sync --extra detectors
uv run pytest                                             # correctness tests（synthetic / ray-cast 假資料）
./docker/build.sh && ./docker/run.sh bash docker/smoke.sh # Jazzy + Harmonic 映像與 smoke test
uv run python -m activeperception make-specs --namespace core --groups 300
./docker/render.sh data/episodes/specs-core.json renders/core 4
uv run python -m activeperception build-episodes --world gazebo --specs data/episodes/specs-core.json --renders renders/core
uv run python -m activeperception.detector.run --frames renders/core --detector frcnn-mnv3 --device cuda --out runs/core/detector-v1.jsonl
uv run python -m activeperception.experiment test --episodes data/episodes/gazebo-core.json \
    --detections runs/core/detector-v1.jsonl --renders renders/core --out results/test-v1
uv run python tools/make_figures.py
```

平台版本（image digest、套件版本）見 [`docs/platform/versions.md`](docs/platform/versions.md)；
GPU 工作（detector 推論）在 RTX 5070 Ti 上以共享 GPU lock 執行（[MACHINE_POLICY.md](MACHINE_POLICY.md)）。

## 目錄

```
activeperception/        核心套件：episodes / sim（gz_client、render、replay、raycast）/ sensing / decision /
                         policies / harness / grader / metrics / detector / tune / experiment / pilot
ros_ws/src/inspection_ap_ros/   ROS 2 package（inspector node、launch）
docker/                  Jazzy + Harmonic 映像、render / smoke / ROS 線上執行腳本
gazebo/models/           vendored Fuel 模型（fire_hydrant，CC0）
data/episodes/           frozen spec / episode sets（含 GT）
results/                 detector 選型、pilot、調參、正式 test
docs/decisions/          decision logs 001–010
```

## 限制

- 場景刻意簡化（方柱遮擋、固定光照、單一目標類別）；detector 在此 world 幾乎不誤報，perception 偏容易。
- `decision-v1` 的 absent 規則較寬；test 上 Random 出現一例 false absent，Rule / Oracle 沒有。
- 多視角方法的 definitive decision confidence 校準不佳（ECE 0.21–0.38；Single 0.016）：absent 的 confidence = coverage × (1 − c_max)，公式在 v1 凍結未改。
- Core 只用 teleport；Nav2（Advanced B）尚未進行，是否進行由使用者決定。
