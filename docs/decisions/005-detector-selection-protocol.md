# 005 — Core detector 選型協定（預先登錄）

- **日期**：2026-10-13
- **狀態**：**協定凍結，選型結果待填**（結果另以附錄記錄於本檔，並在選定後凍結為 `detector-v1`）
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

## 執行地點

- 準確率指標（P、S1–S4）與裝置無關，在可取得的機器上跑：`gpu-server`（GPU lock）優先；若 `gpu-server` 不可用，改在 Mac 執行（小型推論，MACHINE_POLICY 允許），並在結果附錄記錄硬體。
- R1 的 GPU 延遲只能在 `gpu-server` 量；不可用時標記 deferred，不影響選擇規則（規則不使用 GPU 延遲）。

## 被凍結的項目

候選模型清單、資料來源與 namespace、推論設定、指標定義、選擇規則。
