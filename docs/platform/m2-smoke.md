# M2 smoke test（2026-10-13，Mac arm64，Docker Desktop 29.8.1）

指令：`./docker/run.sh bash docker/smoke.sh`（容器 `inspection-ap-sim:jazzy-harmonic`，image id 見 `versions.md`）。
場景：`pilot-g0000-v0`（gen-v2，消防栓 + 2 根遮擋柱，初始視線被擋）。

| 檢查 | 結果 |
|---|---|
| `gz sim -s -r --headless-rendering`（ogre2，EGL surfaceless，llvmpipe） | 可用，約 3 s 內三個 sensor 都有 frame |
| 格式 | RGB `RGB_INT8` 480×640×3；depth `R_FLOAT32`；labels `RGB_INT8`，三通道相同，背景 = 0 |
| depth 無回波 | `+inf`（天空）；遠截 20 m |
| teleport（`/world/inspection/set_pose/blocking`，static 相機模型） | 生效，視角改變 |
| 新鮮度 | 每張 frame 的 stamp 都晚於 teleport 參考時間 + 0.25 s |
| 同一 pose 重 render（中間繞去其他視角） | RGB / depth / labels **逐像素相同** |
| 速度 | 每個 viewpoint 約 0.30 s（10 Hz sensor，RTF 1） |

## 已知限制與處理

- Python bindings 若訂閱 `/world/<w>/clock`（每個 physics step 發布，約 250 Hz），服務請求全部逾時且程式結束時 segfault。
  `gz_client` 因此不訂閱 clock，改以最新 frame 的 stamp 當 teleport 參考時間（見 `activeperception/sim/gz_client.py` docstring）。
- gz-transport 服務 discovery 需要時間：`GzClient._request` 在 discovery 期間重試（最長 20 s）。

結論：decision 001 方案 A（Mac arm64 容器）可行，不需要方案 B（gpu-server amd64）。
