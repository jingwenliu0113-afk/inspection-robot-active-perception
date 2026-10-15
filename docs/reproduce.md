# 重現指南

分四個層級，越往下越完整、越花時間。下表的時間是在 Apple M4 Pro（48 GB）、Docker Desktop 上量到的。

| 層級 | 需要 | 時間 | 能檢查什麼 |
|---|---|---|---|
| **A. 不需 Docker** | `uv`、Python 3.12 | 數分鐘 | 測試、封存檔未被改動、所有 spec 逐位元重新產生、大部分圖表從已 commit 的結果重畫 |
| **B. Demo** | Docker Desktop、Nav2 映像、detector 權重 | 建映像後每集約 1–1.5 分鐘 | 一集真正的 Nav2 閉迴路，並輸出動畫 |
| **C. Core 完整重現** | Docker（模擬映像）、約 1.3 GB 的 render | render 約 0.3 s / 視角 | 重新 render，並對已封存的 test / holdout 做逐位元比對 |
| **D. Advanced B 完整重現** | Nav2 映像 | `nav-b2` 960 次閉迴路約 2 h 17 min（4 容器並行） | 重新執行 B0–B2；Nav2 不是逐位元可重現（見 §D） |

> **封存規則**：原 `core` test 與 `holdout` 都已用過一次。正式 runner 對它們只接受 `--reproduce`；這個模式的輸出不得寫進 `results/`，
> 程式只比對 `outcomes.jsonl` 是否與已 commit 的版本逐位元相同。`nav-b2` 也已用過，不得再用於任何開發或調參。

## A. 不需 Docker

```bash
uv sync --extra detectors
uv run pytest                                      # correctness tests（synthetic world / 解析 ray-cast）
uv run ruff check .
uv run python -m activeperception.seal verify      # 封存的結果、episode sets、frozen.py / frozen_v2.py 沒被改動
```

場景產生器是 seeded 的，所有 spec 都能重新產生，並與 repo 內的版本逐位元相同：

```bash
uv run python -m activeperception make-specs --namespace core --groups 300 --out /tmp/specs-core.json
cmp /tmp/specs-core.json data/episodes/specs-core.json
uv run python -m activeperception make-specs --namespace holdout --groups 150 --out /tmp/specs-holdout.json
cmp /tmp/specs-holdout.json data/episodes/specs-holdout.json
uv run python -m activeperception.nav.scene --namespace nav-b2 --groups 40 --out /tmp/specs-nav-b2.json
cmp /tmp/specs-nav-b2.json data/episodes/specs-nav-b2.json
```

圖表只讀已 commit 的結果。`three_states.png` 與 `failure_case.png` 需要相機影像（`renders/`，不在 git 裡），沒有影像時會自動跳過：

```bash
uv run python tools/make_figures.py
```

失敗分析的結果也已 commit：Core 的在 [`results/failure-analysis/summary.json`](../results/failure-analysis/summary.json)，
Nav2 的在 [`results/nav-failure-analysis/summary.json`](../results/nav-failure-analysis/summary.json)，說明見 [failure-analysis.md](failure-analysis.md)。

## B. Demo：一集真正的 Nav2 閉迴路

```bash
./docker/build.sh && ./docker/build_nav.sh && ./docker/build_navdet.sh   # 只需一次；navdet 映像約 5.8 GB
mkdir -p models && curl -L -o models/fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth \
  https://download.pytorch.org/models/fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth   # 載入時驗證 sha256
./docker/demo.sh                     # nav-b1-g0001-v2：起點時消防栓被柱子擋住
./docker/demo.sh nav-b1-g0001-v3     # 同一場景，沒有消防栓
```

輸出在 `runs/demo/`：每一步的影像、Nav2 / driver log、`run.json`，以及動畫 `runs/demo/<episode>.gif` 與分鏡 `.png`。
README 的 Demo 圖就是這兩個指令在 2026-10-14 的輸出。

- Demo 只用開發資料 `nav-b1`，不碰正式評估資料。
- 動畫工具會用可部署的資料重建每一步的判定輸入，並與 `run.json` 比對，不一致就直接失敗。
- 圖上的路徑、機器人位置與消防栓位置來自模擬器真實值，只用於畫圖。

## C. Core 完整重現

```bash
./docker/build.sh
./docker/run.sh bash docker/smoke.sh                                   # headless render、teleport、決定性
./docker/render.sh data/episodes/specs-pilot.json renders/pilot 3       # 約 14 MB；three_states.png
./docker/render.sh data/episodes/specs-core.json renders/core 4         # 約 760 MB
./docker/render.sh data/episodes/specs-holdout.json renders/holdout 4   # 約 385 MB
uv run python -m activeperception build-episodes --world gazebo \
    --specs data/episodes/specs-core.json --renders renders/core --out /tmp/gazebo-core.json   # GT 來自語意標籤
```

同一個 pose 重新 render 會得到逐像素相同的 RGB / depth / labels（跨容器、跨機器都已驗證，見 [decision 007](decisions/007-gazebo-observation-pipeline.md)）。

### 偵測

正式偵測是在 RTX 5070 Ti（CUDA）上產生的，已 commit 為 `results/core/detector-v1.jsonl` 與 `results/holdout/detector-v1.jsonl`。
在 CPU 上重跑時，confidence 最多相差 0.004，接近門檻的少數判定可能因此不同，所以逐位元比對一律使用已 commit 的偵測檔。要自己跑：

```bash
uv run --extra detectors python -m activeperception.detector.run --frames renders/core --detector frcnn-mnv3 \
    --device cpu --out /tmp/core-detector-v1.jsonl
```

### 逐位元比對封存的正式結果

```bash
uv run python -m activeperception.experiment test --episodes data/episodes/gazebo-core.json \
    --detections results/core/detector-v1.jsonl --renders renders/core --out /tmp/repro-test-v1 --reproduce
uv run python -m activeperception.experiment_v2 holdout --episodes data/episodes/gazebo-holdout.json \
    --detections results/holdout/detector-v1.jsonl --renders renders/holdout --out /tmp/repro-holdout --reproduce
```

拿掉 `--reproduce`，或把 `--out` 指到 `results/` 底下，程式都會拒絕執行。

### 開發階段的指令（只用 core train / val）

```bash
uv run python -m activeperception.tune decision --episodes data/episodes/gazebo-core.json \
    --detections results/core/detector-v1.jsonl --renders renders/core --out /tmp/tuning      # v1（decision 008）
uv run python -m activeperception.tune decision2 --episodes data/episodes/gazebo-core.json \
    --detections results/core/detector-v1.jsonl --renders renders/core --out /tmp/tuning-v2   # v2（decision 011）
uv run python -m activeperception.failure_analysis --out /tmp/failure-analysis \
    --dev-episodes data/episodes/gazebo-core.json --dev-detections results/core/detector-v1.jsonl \
    --dev-renders renders/core
```

`tune` 拒絕 test 與 holdout split。ROS 2 線上版的一致性檢查見 [`results/pilot/`](../results/pilot/) 與 [`results/pilot-v2/`](../results/pilot-v2/)。

## D. Advanced B 完整重現

```bash
./docker/build_nav.sh && ./docker/build_navdet.sh
./docker/nav_smoke.sh                                         # TurtleBot 4 + Nav2 + Harmonic 相容性
# B0（decision 015 / 016）：12 集固定計畫的導航
./docker/nav_b0.sh 3 nav-b0-g000{0..5}-v{0,1}
uv run --extra detectors python -m activeperception.nav.b0_analysis --runs runs/nav-b0 --out /tmp/nav-b0
# B2（decision 018）：teleport 對照 + Nav2 閉迴路
./docker/render.sh data/episodes/specs-nav-b2.json renders/nav-b2 4
uv run python -m activeperception build-episodes --world gazebo \
    --specs data/episodes/specs-nav-b2.json --renders renders/nav-b2 --out /tmp/gazebo-nav-b2.json
uv run --extra detectors python -m activeperception.detector.run --frames renders/nav-b2 \
    --detector frcnn-mnv3 --device cpu --out runs/nav-b2/teleport-detector-v1.jsonl
./docker/nav_b1.sh 4 nav-b2                                   # 960 個工作；中斷後重跑同一指令即可續跑
uv run python -m activeperception.nav.b1_analysis --ns nav-b2 --out /tmp/nav-b2
uv run python -m activeperception.nav.failure_analysis --out /tmp/nav-failure-analysis
```

`nav-b0c`、`nav-b0d` 的指令見各自的 `results/*/README.md`（`OUT=runs/nav-b0c ./docker/nav_b0.sh …`、`RELOCALIZE=1`）。

**Nav2 的結果不是逐位元可重現的**：
- 原因：Nav2、AMCL 與 Gazebo 的時序在每次執行都略有不同，機器人停下的位置有公分級差異。
- 影響：可能改變之後的視角選擇。例如 `nav-b1-g0001-v3` 在 B1 用了 3 個視角，Demo 重跑用了 4 個，兩次的判定都是 `absent`。
- 對結論的影響：B2 的結論是統計上的（160 集、cluster bootstrap），重跑應得到相近、但不相同的數字。
- 正式結果：只有 decision 019 記錄的那一次是正式評估。

## E. R0 真實環境適應研究

- **R0a（真實照片）**：Open Images 的 metadata 與影像約 0.6 GB（影像只存在本機）。選樣、下載、偵測、報告的指令見 [`results/r0a/README.md`](../results/r0a/README.md)。
  train 框標註的取得方式見 decision 020 附錄 A。偵測只需 CPU（983 張、兩種解析度，約 8 分鐘）。
- **R0b（模擬誤差）**：render 160 集約 4 分鐘、偵測約 5 分鐘，18 個條件約 23 分鐘（10 個行程）。指令見 [`results/r0b/README.md`](../results/r0b/README.md)。
  誤差以 (episode, 視角, 等級) 固定 seed 抽樣，重跑會得到相同的誤差。
- 兩者的正式資料都已用過；重跑時把輸出指到 `results/` 以外（程式在正式結果已存在時拒絕覆寫）。

## F. v3、A、B

- **v3（模擬誤差，decision 024–026）**：
  - 開發：`python -m activeperception.v3.eval --ns v3-dev ...`。只接受開發 namespace，指令與所有開發結果見 [docs/v3-development.md](v3-development.md)。
  - 正式：
    1. 產生資料：`python -m activeperception.nav.scene --namespace v3 --groups 40` 與 `python -m activeperception.v3.scenes --namespace v3-dx --groups 40`；
    2. `./docker/render.sh` 渲染，`build-episodes` 建 GT，`detector.run` 跑偵測；
    3. 執行 `python -m activeperception.v3.formal --out results/v3 --raw runs/v3-formal`。`results/v3` 已存在時會拒絕重跑。
  - 12 個 job，Mac 12 核約 1 小時。
- **A（detector-v2，decision 027）**：
  - 資料：`python -m activeperception.detv2.data split / download`，test 清單不允許提早下載。
  - 訓練：`tools/detv2_gpu.sh`（RTX 5070 Ti，GPU lock）。
  - 選擇與正式評測：`python -m activeperception.detv2.formal dev / select / test`。
- **B（depth 模型檢查，decision 028）**：
  1. `python -m activeperception.depthnoise.osf`：OSF 公開資料，186 MB，CC BY 4.0；
  2. `python -m activeperception.depthnoise.planes --out results/depthnoise/planes.json`：約 10 秒；
  3. `python -m activeperception.depthnoise.compare results/depthnoise/planes.json`。

## G. v4 與 D3 的正式驗證（decision 029 / 031）

- 開發：`python -m activeperception.v3.eval --ns v3-dev --configs w4hjg8 ...`（v4 的設定在 `activeperception/v4/configs.py`，共用 v3 的 harness）；
  摘要：`python -m activeperception.v4.devreport runs/v4-dev/...`。所有開發結果見 [docs/v4-development.md](v4-development.md)。
- 正式：
  1. `python -m activeperception.nav.scene --namespace v4 --groups 40` 與 `python -m activeperception.v3.scenes --namespace v4-dx --groups 40`；
  2. `./docker/render.sh` 渲染（各 4 個容器約 4 分鐘），`build-episodes` 建 GT，`detector.run` 跑 `detector-v1`；
  3. `python -m activeperception.v4.formal --out results/v4 --raw runs/v4-formal`。`results/v4` 已存在時會拒絕重跑。
- 16 個 job（v3 與 v4 各 8 個條件）；v4 的精修每個視角約 2 秒。

## H. v5：see-v5（decision 033 / 034）

- 開發：`python -m activeperception.v5.dev --ns v3-dev --cal-ns v3-dev-dx --conditions D3xL1,... --bands v4+k14 --out runs/v5-dev/seek`
  （`v4+k14` = 凍結 v4 ＋ see-v5；`v4+k14+free` = 不包住；`f0.02` 等 = 比例自我校正的假設帶，校正值由 `python -m activeperception.v5.calib` 產生）；
  比較：`python -m activeperception.v5.devreport runs/v5-dev/seek`（`--dx` 對照 `v3-dev-dx` 的 v4 基準）。開發結果見 [docs/v5-development.md](v5-development.md)。
- 正式：
  1. `python -m activeperception.nav.scene --namespace v5 --groups 40` 與 `python -m activeperception.v3.scenes --namespace v5-dx --groups 40`；
  2. 渲染、建 GT、`detector-v1`（同 §G）；
  3. `python -m activeperception.v5.formal --out results/v5 --raw runs/v5-formal`。`results/v5` 已存在時會拒絕重跑；Mac heavy lock 被持有時不啟動，執行中被取得時下一個 job 等鎖釋放。
- 24 個 job（v4、v5、v5 不包住各 8 個條件）。

## 資源與隔離

- 所有容器都叫 `inspection-ap-*`，各自有獨立的 network namespace，ROS 2 discovery 限制在 localhost。不碰其他專案的容器、網路與 volume，也不做全域的 Docker prune。
- 大型批次執行前會檢查 `/tmp/ai-portfolio-mac-heavy.lock`；其他專案持有這個鎖時就不執行（[MACHINE_POLICY.md](../MACHINE_POLICY.md)）。
- 版本與 image digest：[docs/platform/versions.md](platform/versions.md)、[versions-nav.md](platform/versions-nav.md)。
