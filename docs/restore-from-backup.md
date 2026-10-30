# 從備份還原本機資料（延伸研究前）

2026-10-30 因為 Mac 空間不足，本機只在 Mac 上的資料打包成私人備份放到 Google Drive，之後刪除本機專案資料夾與本專案的 Docker 映像。
GitHub 上已有全部程式、文件、decision log、結果（含封存的）、episode spec 與偵測快取（[`results/detections/`](../results/detections/README.md)）；
下列備份只補「不在 git 裡」的資料。

## 1. 備份內容

Google Drive 資料夾：`inspection-ap-backup-2026-10-30`（私人，不得公開分享：`data-raw.tar` 內有授權不允許再散布的照片）。

| 檔案 | 大小 | 檔案數 | 還原後的位置 | 內容 | 能否不靠備份重建 |
|---|---|---|---|---|---|
| `runs.tar` | 762 MB | 14,119 | `runs/` | detector-v2 的三組訓練權重（`runs/detv2/*/weights.pth`）、偵測快取、Nav2 閉迴路原始紀錄（`nav-b*`）、開發與正式評估的逐視角輸出、各種 log | **權重不能**（GPU 訓練不會得到相同權重）；偵測快取已在 `results/detections/`；其他可重跑但要數小時 |
| `data-raw.tar` | 1.92 GB | 5,554 | `data/raw/` | R0a / detector-v2 的 Open Images 與 COCO 照片、OSF 的 RealSense depth 原始檔 | 大致可以重新下載（`activeperception.r0a`、`detv2.data`、`depthnoise.osf`），但照片網址可能失效 |
| `renders.tar` | 3.13 GB | 11,267 | `renders/` | 所有 namespace 的 Gazebo render | 可以：重新 render 與原本逐像素相同（reproduce §C 實測），全部約 1.5–2 小時 |
| `models-frcnn.tar` | 78 MB | 1 | `models/` | `detector-v1` 權重（torchvision FRCNN-MobileNetV3，BSD-3-Clause） | 可以：從 `download.pytorch.org` 下載，載入時驗證 sha256（reproduce §B） |

校驗碼（同資料夾的 `SHA256SUMS`、`MD5SUMS`；建立時已逐檔比對 30,134 個檔案與本機內容相同）：

```
148574028ba707c89fb147363df13fd664e6a1929f799ab576597771c9d7e421  runs.tar
8edd65007cf0a04938f6e37e07c9ab3126acce66f87a5bba265dbfe6c004ed35  data-raw.tar
3f702095ff206881b0f288587efb3aa9aca9e8b2227227c1edce3cc3bd8c188e  renders.tar
e7c0d260aba29dde5564a1adf39b7303b888635dd741ba7acc5e9ec86a79ba7e  models-frcnn.tar
```

**沒有備份**的東西：`.venv`（`uv sync` 重建）、YOLO 權重（AGPL，已不使用）、本專案的 4 個 Docker 映像（用 Dockerfile 重建）、
`ros_ws/build` 等建置輸出、`__pycache__`、`data/episodes/synthetic-dev.json`（synthetic world，`make-specs` 重建）。

## 2. 還原步驟

```bash
# 1. 程式與結果（建議 clone 回原本的 ~/Desktop/AI-Portfolio/inspection-robot-active-perception，Claude Code 的專案記憶以路徑對應）
git clone https://github.com/jingwenliu0113-afk/inspection-robot-active-perception.git
cd inspection-robot-active-perception

# 2. 從 Google Drive 下載需要的 .tar 與 SHA256SUMS 到 repo 根目錄，驗證
shasum -a 256 -c SHA256SUMS            # 只下載部分檔案時，忽略「找不到檔案」的那幾行

# 3. 解壓（路徑都相對於 repo 根目錄），然後刪掉 .tar
tar -xf runs.tar && tar -xf data-raw.tar && tar -xf renders.tar && tar -xf models-frcnn.tar

# 4. Python 環境與檢查
uv sync --extra detectors
uv run python -m activeperception.seal verify
uv run pytest                           # renders/core 還原後，v1 regression 不再跳過

# 5. Docker 映像（需要網路；Docker Desktop 執行中）
./docker/build.sh && ./docker/build_nav.sh && ./docker/build_navdet.sh
./docker/demo.sh                        # 一集 Nav2 閉迴路，確認環境正常
```

- 沒有還原 `renders.tar` 時：照 [reproduce.md §C](reproduce.md#c-core-完整重現) 重新 render，並用 `rsync -a results/detections/ runs/` 放回偵測快取。
- **Docker 映像重建後的版本**：Dockerfile 固定了 ROS 2 / Gazebo / torch 的版本，但 apt 會取當時最新的修補版。
  延伸研究若要和既有結果做正式比較，先對照 [platform/versions.md](platform/versions.md)、[versions-nav.md](platform/versions-nav.md) 記錄的版本與 image digest；
  不一致時先在開發資料上確認輸出相同（例如 `./docker/run.sh bash docker/smoke.sh` 與 core val 的重新 render 逐像素比對），再進行任何正式實驗。
- 延伸研究前也要依 `CLAUDE.md` 的流程：讀 NEXT.md 的 Future Work，任何新方向先由使用者決定、先寫 decision log；封存的資料與結果不得修改。
