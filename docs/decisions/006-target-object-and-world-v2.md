# 006 — 目標物件與 world v2（generator `gen-v2`）

- **日期**：2026-10-13
- **狀態**：已決定（pilot 前；pilot 若發現問題只能另開 decision log 修正）
- **是否在看過正式結果後才新增 / 修改**：否，尚無任何正式結果，也尚未跑過任何 detector。

## 問題

`gen-v1` 的目標是浮在 zone 中心高度（0.6 m）的球體，只是 synthetic world 的幾何替身。
使用者 2026-10-13 決定 Core detector 從 COCO 預訓練模型（YOLOv8m / YOLO11m / torchvision Faster R-CNN MobileNetV3）中選一個（decision 005），
所以 Gazebo world 裡的目標必須是 **COCO 類別**、有真實外觀的物件，而且要站在地上。

`gen-v1` 另有兩個幾何缺陷（synthetic 時不明顯）：

1. 遮擋柱中心半徑 0.85–1.3 m、寬度到 0.8 m，柱子可能伸進 inspection zone（半徑 0.5 m），甚至把目標包在柱子裡。
2. 柱子外緣可能到 1.87 m，候選相機環最小半徑 1.8 m，相機可能落在柱子裡。

## 候選方案（Gazebo Fuel，2026-10-13 查詢）

| 物件 | Fuel model | 授權 | COCO 類別 | 評估 |
|---|---|---|---|---|
| 消防栓 | `OpenRobotics/Fire hydrant` v3 | CC0 | fire hydrant | 巡檢主題吻合；COCO 中辨識度高的類別；大小適中 |
| 行李箱 | `OpenRobotics/Suitcase1` / `Suitcase2` | CC0 | suitcase | 備案；外觀較單調 |
| 背包 | `OpenRobotics/Backpack`（SubT artifact） | CC0 | backpack | COCO backpack 類別本身難偵測，會讓 perception 主導誤差 |
| 椅子 | `OpenRobotics/Chair` 等 | CC-BY 4.0 | chair | 尺寸偏大、需標註來源 |

## 決定

### 目標物件

- `OpenRobotics/Fire hydrant`，Fuel version 3，CC0。模型檔 vendored 到 `gazebo/models/fire_hydrant/`（離線、可重現），來源 URL 與 sha256 記在該目錄的 `SOURCE.md`。
- mesh 單位為公分（COLLADA `unit meter=0.01`），換算後約 0.42 × 0.42 × 0.93 m；實際 render 尺寸在 M2/M3 以 segmentation 量測後補記。
- 直立放在地面（z = 0），yaw 在 [0, 2π) 均勻抽樣，中心在半徑 `zone.radius − object_radius` 的圓盤內均勻抽樣；`object_radius` = 0.21 m（底面外接半徑）。

### Inspection zone

- 圓柱：中心 (0, 0)，半徑 0.5 m，z ∈ [0, 0.95] m（`InspectionZone.height`）。相機 look-at 目標點為 (0, 0, 0.45)。
- 部署時已知的資訊只有這個圓柱（「去檢查這一塊區域」），與物件存在與否無關。

### 遮擋柱（修正 gen-v1 的兩個缺陷）

- 1–3 根方柱，寬度 0.3–0.6 m（原 0.4–0.8），高度 0.9–1.5 m（不變）。
- 中心半徑依寬度條件抽樣：`r ∈ [zone.radius + hd + 0.05, ring_min − hd − 0.15]`，`hd` = 方柱半對角線 = w/√2，`ring_min` = 1.8 m。
  保證柱子不侵入 zone、不碰到任何候選相機位置。
- 50% 的 scene group 會刻意把一根柱子放在初始視線上（方位 ±4°），與 gen-v1 相同；這是控制 layout，不是用 GT 篩選。

### Variants 配對（修正 gen-v1 的實作與註解不一致）

gen-v1 的程式註解宣稱同一對 present / absent 的遮擋柱 jitter 相同，但 v2 與 v3 的亂數流以 variant 編號為 key，實際上 jitter 不同。
gen-v2 改為 jitter 以 `variant // 2` 為 key：v0 / v1 共用基礎佈局，v2 / v3 共用同一組 jitter 後的佈局，每一對只差在物件存在與否（matched pair）。
物件位置與 yaw 以 variant 為 key 另外抽樣。

### 不變的部分

候選 viewpoint（12 個、半徑 2.0 ± 0.2、高度 1.1 ± 0.2、只依 namespace / generator version / scene group）、初始 viewpoint、
4 variants 結構、split 規則與比例、budget 計數方式、labeling `label-v1`（visible 門檻 0.5）全部沿用 decision 002。
因為 generator version 是 split hash 的一部分，`gen-v2` 的 split 分配與 `gen-v1` 不同（尚無結果，無影響）。

### Namespace 用途（seed 流互相獨立）

| namespace | 用途 |
|---|---|
| `dev` | synthetic world 開發 / 測試 |
| `pilot` | SPEC §9 pilot（永遠是 PILOT split，不進 final test） |
| `detsel` | detector 選型資料（decision 005），不屬於 train / val / test |
| `core` | 正式 episode set（train / val / test） |

### Synthetic world

synthetic world 用垂直圓柱（半徑 0.15 m、高 0.93 m）當消防栓替身，只用於 correctness tests 與開發，不是結果來源（decision 001）。

## 被凍結的項目

`gen-v2`：目標物件與版本、放置規則、zone 圓柱、遮擋柱抽樣規則與條件、namespace 用途。
