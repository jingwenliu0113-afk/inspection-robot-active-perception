# R0a：凍結的 detector 在真實照片上（decision 020 / 021）

**這是真實影像驗證，不是機器人相機，也不是實機驗證。** 判準在跑 detector 之前凍結（decision 020），結果與判定見 [decision 021](../../docs/decisions/021-r0a-result.md)。

- 資料：Open Images V7（train + test），人工驗證的消防栓正 / 負標籤。
  - 正式集 383 張含消防栓（clear 243）＋ 600 張人工確認不含（偏難的負樣本）。
  - 與 COCO 2017 重疊的照片已排除（detector 的訓練來源）。
  - 清單與姓名標示：[`data/r0a/manifest-formal.csv`](../../data/r0a/manifest-formal.csv)（影像 ID、作者、CC BY 2.0、原始網址）。影像不在 repo 內。
- detector：`detector-v1`（FRCNN-MobileNetV3，COCO 預訓練、未微調），CPU；門檻沿用凍結的 `decision-v2`（present ≥ 0.7、absent 需要 < 0.02）。
- 主要結果用「約 640×480 像素數」的版本（與模擬相機相同解析度）；原始解析度只作參考。

![R0a](../../docs/figures/r0a_real_images.png)

## 判定

| # | 判準 | 結果 | 判定 |
|---|---|---|---|
| A1 | clear 消防栓 localized recall@0.7 ≥ 0.90 | 238 / 243 = 97.9% [95.3, 99.1] | **通過** |
| A2 | 偏難負樣本 false present ≤ 0.01 | 55 / 600 = 9.2% [7.1, 11.7] | **未通過** |
| A3 | 偏難負樣本 absent blocked ≤ 0.10 | 287 / 600 = 47.8% [43.9, 51.8] | **不可用** |

一句話：看得清楚的真實消防栓幾乎都認得出來，也幾乎不會完全漏看。但外觀相近的物體（郵筒、閥門、立管、路樁）會被誤判成消防栓，
而目前的判定規則取整張影像的最高信心，不管偵測框是否在 inspection zone 內。實機之前必須先處理這一點。

## 完整表格

### 含消防栓的影像：約 640×480 像素數（主要）

| 層 | localized recall@0.7 | present rate | complete miss（< 0.02） |
|---|---|---|---|
| clear | 238 / 243 = 97.9% [95.3, 99.1] | 240 / 243 = 98.8% [96.4, 99.6] | 0 / 243 = 0.0% [0.0, 1.6] |
| small | 4 / 7 = 57.1% [25.0, 84.2] | 4 / 7 = 57.1% [25.0, 84.2] | 0 / 7 = 0.0% [0.0, 35.4] |
| truncated | 74 / 83 = 89.2% [80.7, 94.2] | 76 / 83 = 91.6% [83.6, 95.9] | 0 / 83 = 0.0% [0.0, 4.4] |
| occluded | 42 / 46 = 91.3% [79.7, 96.6] | 44 / 46 = 95.7% [85.5, 98.8] | 0 / 46 = 0.0% [0.0, 7.7] |
| main | 358 / 379 = 94.5% [91.7, 96.3] | 364 / 379 = 96.0% [93.6, 97.6] | 0 / 379 = 0.0% [0.0, 1.0] |

不含消防栓（人工驗證、偏難的負樣本）：false present 55 / 600 = 9.2% [7.1, 11.7]；absent blocked 287 / 600 = 47.8% [43.9, 51.8]；AP50 0.936

### 含消防栓的影像：原始解析度（參考）

| 層 | localized recall@0.7 | present rate | complete miss（< 0.02） |
|---|---|---|---|
| clear | 239 / 243 = 98.4% [95.8, 99.4] | 242 / 243 = 99.6% [97.7, 99.9] | 0 / 243 = 0.0% [0.0, 1.6] |
| small | 4 / 7 = 57.1% [25.0, 84.2] | 4 / 7 = 57.1% [25.0, 84.2] | 0 / 7 = 0.0% [0.0, 35.4] |
| truncated | 72 / 83 = 86.7% [77.8, 92.4] | 73 / 83 = 88.0% [79.2, 93.3] | 0 / 83 = 0.0% [0.0, 4.4] |
| occluded | 42 / 46 = 91.3% [79.7, 96.6] | 44 / 46 = 95.7% [85.5, 98.8] | 0 / 46 = 0.0% [0.0, 7.7] |
| main | 357 / 379 = 94.2% [91.4, 96.1] | 363 / 379 = 95.8% [93.3, 97.4] | 0 / 379 = 0.0% [0.0, 1.0] |

不含消防栓（人工驗證、偏難的負樣本）：false present 55 / 600 = 9.2% [7.1, 11.7]；absent blocked 280 / 600 = 46.7% [42.7, 50.7]；AP50 0.939

### 人工遮擋（clear 正樣本，camera 版本）

| 遮住框寬 | present rate | complete miss |
|---|---|---|
| 0% | 240 / 243 = 98.8% [96.4, 99.6] | 0 / 243 = 0.0% [0.0, 1.6] |
| 25% | 238 / 243 = 97.9% [95.3, 99.1] | 0 / 243 = 0.0% [0.0, 1.6] |
| 50% | 211 / 243 = 86.8% [82.0, 90.5] | 1 / 243 = 0.4% [0.1, 2.3] |
| 75% | 58 / 243 = 23.9% [18.9, 29.6] | 42 / 243 = 17.3% [13.0, 22.5] |

### 判準（decision 020 §7）

| # | 結果 | 判定 |
|---|---|---|
| A1 clear localized recall@0.7 ≥ 0.90 | 238 / 243 = 97.9% [95.3, 99.1] | 通過 |
| A2 false present ≤ 0.01 | 55 / 600 = 9.2% [7.1, 11.7] | **未通過** |
| A3 absent blocked（≤ 0.10 視為可用） | 287 / 600 = 47.8% [43.9, 51.8] | **不可用** |


## 重現

```bash
uv run python -m activeperception.r0a select --meta data/raw/r0a/meta --coco-flickr data/raw/r0a/coco/flickr_ids.txt --out data/r0a
uv run python -m activeperception.r0a download --manifest data/r0a/manifest-formal.csv --images data/raw/r0a/images
uv run --extra detectors python -m activeperception.r0a detect --manifest data/r0a/manifest-formal.csv \
    --images data/raw/r0a/images --out /tmp/r0a-detections.jsonl        # 正式結果已存在時，results/ 底下拒絕重跑
uv run python -m activeperception.r0a report --manifest data/r0a/manifest-formal.csv \
    --detections results/r0a/detections-formal.jsonl --out /tmp/r0a
```

metadata 的取得方式（含 train 框標註的索引式下載）見 decision 020 附錄 A。
