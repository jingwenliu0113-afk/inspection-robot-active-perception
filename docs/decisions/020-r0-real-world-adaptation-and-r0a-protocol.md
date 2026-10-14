# 020 — R0 真實環境適應研究：範圍，與 R0a（真實影像 detector 驗證）協定（預先登錄）

- **日期**：2026-10-14
- **狀態**：R0a 協定凍結；寫於任何 detector 在 R0a 影像上執行之前。資料的 metadata 統計見附錄 A（只看標註，沒看 detector 輸出）。
  R0a 結果另寫 decision 021；R0b 協定在 R0a 完成後另寫。
- **是否在看過正式結果後才新增 / 修改**：否——R0 沒有任何結果。Core（001–014）與 Advanced B（015–019）的資料、結果、Gate 與封存全部不變。

## 1. 使用者決定（2026-10-14）

1. 依序進行 R0a、R0b，作為**獨立的真實環境適應研究**；控制範圍，不擴充成新的大型專案。
2. R0a：用**合法取得的真實消防栓影像**驗證已選定的 detector（`detector-v1`）的辨識能力。
3. R0b：模擬合理的 depth 感測器雜訊與定位誤差，測試 v2 是否仍能避免 false absent。
4. 不指定場地、不購買機器人、不進 RL。
5. 使用新的獨立資料；先凍結評測標準；不修改 Core / Advanced B 已封存的結果。
6. 資料規模：選擇以串流方式過濾 Open Images train 的框標註（約 2.26 GB 傳輸、只保留消防栓列），再下載所需影像。

## 2. 三種驗證不得混為一談

| 名稱 | 內容 | 能回答 | 不能回答 |
|---|---|---|---|
| **R0a 真實影像驗證** | 網路上的真實照片（Open Images）＋ 凍結的 detector | detector 對真實世界的消防栓外觀、背景、光照是否仍可靠；凍結門檻在真實影像上的誤報率 | 機器人相機（解析度、俯角、動態模糊、曝光）下的表現；depth、定位、導航 |
| **R0b 模擬雜訊測試** | Gazebo 影像 ＋ 依規格建模的 depth 雜訊與定位誤差 | v2 的安全保證對「模型化的」雜訊是否穩健 | 真實感測器的所有誤差型態 |
| **實機驗證** | 實體機器人、實際場地 | 端到端的真實表現 | — **（未做）** |

README 與所有結果檔都使用這三個名稱分開報告；R0 的任何結果都不得寫成「實機驗證」。

## 3. R0a 資料

- **來源**：Open Images V7 的 boxable 子集（Google；標註 CC BY 4.0，影像依原作者標示為 CC BY 2.0）。
  類別 `Fire hydrant`（`/m/01pns0`）。標註檔：v5 test / validation 框與人工驗證標籤、v6 train 框（串流過濾）、v5 train 人工驗證標籤（串流過濾）、
  2018_04 影像清單（含旋轉、作者、授權、原始網址）。影像從 CVDF 的公開鏡像（`open-images-dataset.s3.amazonaws.com`）下載。
- **保存**：影像只存在本機 `data/raw/r0a/`（git 忽略），不重新散布。repo 只 commit 影像 ID、作者、授權、原始網址（姓名標示）與每張影像的 detector 輸出。
- **與 detector 訓練資料的獨立性**：`detector-v1` 是 torchvision 在 COCO train2017 上訓練的 Faster R-CNN MobileNetV3。
  Open Images 是另一個資料集，但兩者都來自 Flickr，可能有同一張照片。**凡 Flickr 照片 ID 出現在 COCO 2017 train / val 的影像一律排除**（以 COCO 官方標註檔的 `flickr_url` 比對）。
- **分割**：
  - **開發（dev）**：Open Images validation。只用來檢查管線（讀圖、框座標、方向、時間），不調任何東西。
  - **正式（formal）**：Open Images train ＋ test。只跑一次。
- **納入條件**（只依 metadata，與 detector 輸出無關）：
  - 正樣本：該影像有人工驗證的 `Fire hydrant` 正標籤，且至少一個消防栓框。
  - 負樣本：該影像有人工驗證的 `Fire hydrant` 負標籤（人工確認沒有消防栓），且沒有任何消防栓框。
    這些影像通常是某個模型曾經懷疑有消防栓、再由人工否定的，屬於**偏難的負樣本**；結果會照此說明，不代表隨機街景的誤報率。
  - `Rotation` 必須是 0（空白或非 0 排除，避免框與影像方向不一致）。
  - 排除與 COCO 重疊的影像（見上）；下載失敗或無法解碼的影像排除並計數。
- **抽樣**：正樣本全部使用。負樣本從合格的正式負樣本中以固定 seed（20261014，對排序後的 ImageID 用 `numpy.random.default_rng`）抽 600 張；不足 600 則全部使用。

## 4. 正樣本分層（依標註屬性，優先順序由上而下）

| 層 | 定義 |
|---|---|
| depiction | 所有消防栓框都是 `IsDepiction=1`（畫、玩具、模型）→ 不計入主要指標，另外報告 |
| group-only | 所有非 depiction 的框都是 `IsGroupOf=1` → 同上 |
| occluded | 主框（最大的非 depiction、非 group 框）`IsOccluded=1` |
| truncated | 主框 `IsTruncated=1`（被畫面邊緣切掉） |
| unknown | 主框的遮擋或截斷屬性為 −1（標註者未填）→ 不計入主要指標，另外報告 |
| small | 主框面積 < 影像的 2% |
| **clear** | 其餘：未遮擋、未截斷、主框面積 ≥ 2% |

2% 的依據：Core 的相機（640×480）中，消防栓可見像素 ≥ 10k（約 3.3%）時偵測率 99.8%；2–3% 為過渡區，因此把 2% 以下另列為 small。

## 5. 執行

- `detector-v1`（`frcnn-mnv3`，權重 sha256 驗證）、CPU、信心下限 0.001（同 Core），每個影像版本跑一次；輸入為解碼後的 RGB（不套用 EXIF 旋轉，因為只收 `Rotation` = 0）。
- **兩個解析度**：
  - **camera（主要）**：等比例縮小到約 640×480 的像素數（307,200；只縮不放，LANCZOS），與 Core / Advanced B 的相機解析度相當。判準 A1–A3 都用這個版本。
  - **original（參考）**：原始解析度，只描述性報告，用來區分「解析度不足」與「外觀差異」。
- 每張影像存信心最高的 20 個偵測（AP50 以此近似）。
- 判定用門檻**沿用凍結的 `decision-v2`**，不因 R0a 調整：`tau_present` = 0.7、`tau_absent` = 0.02（decision 012）。
- **人工遮擋實驗**（半合成，只用正式 clear 正樣本的 camera 版本）：在主框上蓋一條垂直的灰色長條（RGB 128，模擬柱子），覆蓋框寬的 f ∈ {0.25, 0.5, 0.75}、框的全高；
  從左或右蓋，由 ImageID 的 sha256 決定。這是「真實影像 ＋ 人工遮擋」，結果與自然遮擋分開報告。

## 6. 指標

每張影像取消防栓偵測的最高 confidence `c_max`。

| 指標 | 定義 | 對判定的意義 |
|---|---|---|
| localized recall@0.7 | 存在一個 confidence ≥ 0.7、且與某個消防栓框 IoU ≥ 0.5 的偵測 | 「看得到就判 present」是否成立 |
| present rate | `c_max` ≥ 0.7（不論位置） | 判定規則實際使用的量 |
| complete miss | 正樣本的 `c_max` < 0.02 | detector 完全沒反應：只能靠 depth 看穿判定避免 false absent（R0b 的問題） |
| false present | 負樣本的 `c_max` ≥ 0.7 | 錯誤的肯定答案 |
| absent blocked | 負樣本的 `c_max` ≥ 0.02 | 真的沒有消防栓時，也無法判 absent（只會 `inconclusive`，屬成本） |
| AP50 | 標準框層級 AP（IoU 0.5），正式正負樣本合併 | 參考 |

比例都報 Wilson 95% 信賴區間。

## 7. 預先登錄的判準

| # | 判準 | 通過條件 |
|---|---|---|
| A1 | clear 正樣本的 localized recall@0.7 | ≥ 0.90 |
| A2 | 負樣本的 false present rate | ≤ 0.01 |
| A3 | 負樣本的 absent blocked rate | 報告；≤ 0.10 視為「absent 在真實影像上仍可用」 |
| A4 | occluded / truncated / small、人工遮擋的 recall 與 complete miss | 只報告（描述性） |

解讀（事先寫定）：

- A1、A2 都通過 → 「凍結的 detector 與門檻能辨識**網路照片中清楚可見的**真實消防栓，且在偏難的負樣本上很少誤報」。這**不是**機器人相機或實機的驗證。
- A1 未通過 → 真實部署前需要 Advanced A（以真實影像微調 detector），R0b 照常進行（它不依賴真實影像）。
- A2 未通過 → 凍結的 `tau_present` 在真實影像上有錯誤肯定答案的風險，必須先處理才能考慮實機。
- A3 > 0.10 → 真實影像中「判 absent」很少成立（安全但沒用），記錄為成本。
- A4 的 complete miss 比例說明：在真實影像上，有多少情況必須完全依靠 depth 看穿判定（R0b）才能避免 false absent。

## 8. 不做的事

- 不微調 detector、不改任何門檻、不依 R0a 結果修改 v1 / v2 或 Advanced B 的任何設定。
- 不把 R0a 的數字與 Core / Advanced B 合併或直接比較（影像來源、相機、場景都不同）。
- 正式資料只跑一次；任何後續改進都是新版本、新資料。

## 附錄 A：資料（metadata 統計；跑 detector 之前）

`uv run python -m activeperception.r0a select --meta data/raw/r0a/meta --coco-flickr data/raw/r0a/coco/flickr_ids.txt --out data/r0a`
→ `data/r0a/manifest-{dev,formal}.csv`、`data/r0a/selection.json`。只讀標註與影像清單；寫本附錄時還沒有任何 detector 在這些影像上執行過。

| | dev（validation） | formal（train + test） |
|---|---|---|
| 正樣本 | 12（clear 8、truncated 3、occluded 1） | **383**（clear **243**、truncated 83、occluded 46、small 7、unknown 2、depiction 2） |
| 負樣本 | 8（全部） | **600**（自 2,073 張合格負樣本抽樣） |
| 排除：與 COCO 2017 重疊 | 正 2 | 正 15、負 5 |
| 排除：`Rotation` 空白或非 0 | 正 1、負 2 | 正 70、負 504 |
| 排除：人工驗證為正但沒有框 | 0 | 169（train 的框不是窮舉標註） |
| 授權 | CC BY 2.0：20 / 20 | CC BY 2.0：983 / 983 |

- 資料取得過程：train 的框標註（2.26 GB）第一次單連線串流在約 86% 處逾時中斷；改為利用檔案依 ImageID 排序的特性，以 HTTP Range 建索引、只抓含目標影像的區段（74 MB）。
  train 影像清單（638 MB，未排序）以 8 條連線分段下載並過濾。兩者的結果都與 ImageID 清單核對完整（577 / 577、3,114 / 3,114）。
- 原始標註檔的 sha256 記錄在本機 `data/raw/r0a/meta/SHA256SUMS`；COCO 2017 標註壓縮檔 sha256 `113a836d…470268`（123,287 個 Flickr ID）。
