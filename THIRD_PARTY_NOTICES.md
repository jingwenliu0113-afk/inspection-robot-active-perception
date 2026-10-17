# 第三方內容與授權（Third-party notices）

本專案作者有權授權的**原創程式碼**以 [BSD-3-Clause](LICENSE) 授權。下列第三方內容**不在**該授權範圍內，保留其原有授權。

The original code in this repository that its authors have the right to license is licensed under
[BSD-3-Clause](LICENSE). The third-party content below is not covered by that license and keeps its own license.

## repo 內含的第三方內容

| 內容 | 位置 | 來源與作者 | 授權 |
|---|---|---|---|
| 消防栓 3D 模型（mesh、貼圖、SDF，未修改） | `gazebo/models/fire_hydrant/`（來源與 sha256：`SOURCE.md`） | Gazebo Fuel [`OpenRobotics/Fire hydrant`](https://fuel.gazebosim.org/1.0/OpenRobotics/models/Fire%20hydrant/3) v3；作者 Cole Biesemeyer、Nate Koenig | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| Open Images V7 的標註子集（影像 ID、人工驗證標籤、框座標） | `data/r0a/`、`data/v3/`、`data/detv2/`（`source` 為 `oi-*` 的列）、`results/v3-dev/hard-negatives-dev.csv` | [Open Images Dataset V7](https://storage.googleapis.com/openimages/web/index.html)，Google LLC | 標註：[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| COCO 2017 的標註子集（影像 ID、框座標） | `data/detv2/`（`source` 為 `coco-*` 的列） | [COCO](https://cocodataset.org/)，COCO Consortium | 標註：[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| RealSense D435 / D455 平面 depth 的**衍生統計**（不含原始影像） | `results/depthnoise/` | Rustler et al. 2025, *Empirical Comparison of Four Stereoscopic Depth Sensing Cameras for Robotics Applications*（[arXiv 2501.07421](https://arxiv.org/abs/2501.07421)）；資料 [OSF f2seb](https://osf.io/f2seb/) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

- 標註子集的變更：只挑選與消防栓相關的影像，轉成本專案的 CSV 欄位，框座標只做格式轉換（統一為 x_min, y_min, x_max, y_max），並加上本專案自己的分層與 split 欄位。
- **照片本身不在 repo 內**，只以原始網址引用。每張照片的作者與授權（多數為 CC BY 2.0，少數為 CC BY-SA / BY-NC / BY-ND 等）逐列記在 CSV 的 `author`、`license` 欄位，照片仍適用其各自的授權。
  使用 `activeperception.r0a` / `detv2.data` 下載的照片只存在本機（`data/raw/`，不進 git）。
- `docs/figures/` 的圖都由本專案產生：模擬畫面（Gazebo render，含上表 CC0 的消防栓模型）與已 commit 結果的統計圖；**不含任何第三方照片**。

## 執行時下載、不在 repo 內的內容

| 內容 | 取得方式 | 授權（以原始來源為準） |
|---|---|---|
| detector 權重 `fasterrcnn_mobilenet_v3_large_fpn`（COCO 預訓練） | `download.pytorch.org`，載入時驗證 sha256（docs/reproduce.md §B） | torchvision：BSD-3-Clause |
| detector 選型時比較過的 YOLOv8m / YOLO11m（decision 005，未採用） | **不在本 repo 的程式或依賴中**：轉接程式與 `ultralytics` 依賴已在公開前（2026-10-17）移除，repo 從未包含其程式碼或權重；只保留當時的偵測輸出（`results/detector-selection/`） | Ultralytics：AGPL-3.0（或商業授權） |
| ROS 2 Jazzy、Gazebo Harmonic、Nav2、TurtleBot 4 模擬等 | `docker/Dockerfile*` 從公開套件來源建置映像；repo 只含 Dockerfile | 各套件的授權（多為 Apache-2.0） |
| Python 套件 | `pyproject.toml` / `uv.lock`，由 `uv` 安裝 | 各套件的授權 |
| Open Images 照片、OSF 原始 depth 影像 | 見 docs/reproduce.md §E、§F | 各自的授權（見上） |
