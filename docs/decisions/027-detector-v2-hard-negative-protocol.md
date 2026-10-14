# 027 — detector-v2：困難負樣本微調（協定，預先登錄）

- **日期**：2026-10-15
- **狀態**：協定凍結；寫於任何訓練之前。訓練需要 RTX 5070 Ti（共享 GPU lock），GPU 恢復後執行。結果以新的 decision 報告。
- **是否在看過正式結果後才新增 / 修改**：否。test 清單在本檔之前已產生，但沒有任何 detector 在 test 影像上執行過，test 影像也還沒下載。
- **使用者決定（2026-10-15）**：授權 A「Detector 困難負樣本微調研究」。先完成資料整理、困難負樣本分析、訓練程式與評測設計；今晚不進行需要 RTX 的訓練。
  這解除了 decision 024 中「不重新訓練 detector」的限制，但只限本協定。`detector-v1` 與所有用它得到的結果都保留不變。

## 1. 為什麼需要

- R0a 的 A2 未通過：人工確認不含消防栓的偏難負樣本，false present 9.2%（判準 ≤ 1%；decision 021）。
- v3 開發資料（`docs/v3-development.md` §1）：
  - 只調門檻或框形狀，無法在不大幅犧牲召回的情況下壓低誤報。
  - 67 張誤報中有 26 張是管件、閥門、柱狀街道設施，正是巡檢現場會出現的東西。
- v3 的 zone 過濾只排除 zone **外**的相似物件。zone **內**的相似物件只能靠 detector 本身。

## 2. 資料（`activeperception/detv2/data.py`，清單在 `data/detv2/`）

每張 Open Images 影像都必須符合：CC BY 2.0、Rotation 0、不在 COCO 2017 中（以 Flickr ID 比對）。
COCO 影像在 train / dev 只用允許衍生的授權：CC BY、CC BY-SA、無已知版權。
NC / ND 授權的 COCO 影像只出現在 test，只用於評分，不用於訓練。

| split | 正樣本 | 負樣本 | 用途 |
|---|---|---|---|
| train | COCO train2017 消防栓 426 張（有框） | Open Images 人工確認的負樣本 491 張（v3 開發組的 2/3）＋ 相似物件 545 張 | 訓練 |
| dev | COCO val2017 消防栓 24 張（有框）＋ v3 開發組影像層級正樣本 71 張 | 確認的負樣本 245 張 ＋ 相似物件 273 張 | 選設定、檢查 |
| **test** | COCO val2017 消防栓 62 張（有框，NC / ND，只評分）＋ v3 保留組影像層級正樣本 72 張 | **v3 保留組確認的負樣本 737 張** | 正式評測，只跑一次 |

- **相似物件**：Open Images validation / test 中，有以下類別框、且沒有任何消防栓標籤的影像。每類最多 50 張，兩個 subset 各半。
  - 對應 v3 困難負樣本的四類：
    - 管件：Tap、Fountain。
    - 街道設施：Parking meter、Street light、Waste container、Barrel、Flowerpot、Traffic sign。
    - 雕像：Sculpture、Bust、Doll、Toy、Snowman、Teapot、Vase。
    - 其他：Candle、Lantern、Bottle、Kettle。
- 三個 split 互不重疊（程式檢查）。都不含：
  - R0a 正式集與開發集；
  - 任何模擬資料；
  - 已封存的 Core / B / R0b 資料。
- **剩下有框的 Open Images 消防栓都不符合 R0a 的規則**：66 張缺旋轉資訊、17 張與 COCO 重疊。所以 test 的有框正樣本改用 COCO val2017 中 NC / ND 授權的 62 張。
  `detector-v1` 沒有用 val2017 訓練。
- test 的負樣本與 R0a 正式集的負樣本來自同一個母體（人工確認、合格的偏難負樣本，固定 seed 分半），所以可以直接對照 A2。
- 影像不進 repo（`data/raw/detv2/`）；清單記錄 ID、授權、作者、網址。
- **test 影像只在正式評測時下載**（程式拒絕提早下載 test 清單）。

## 3. 模型與訓練（`activeperception/detv2/train.py`）

架構、類別清單、輸出格式都與 `detector-v1` 相同，只換權重。判定規則、門檻、zone 過濾都不變。

- 初始化：`detector-v1` 的 COCO 權重（以 sha256 檢查）。
- 影像大小：與 R0a / v3 相同的「約 640×480 像素數」。
- 目標：消防栓框是 COCO 的 `fire hydrant` 類別；其他一切都是背景。所以負樣本就是沒有任何目標的影像。
- 骨幹：batch norm 凍結，只訓練最後 3 個 stage。
- 增強：水平翻轉。
- 最佳化：SGD（momentum 0.9、weight decay 1e-4），batch 4，8 個 epoch，200 iter warmup 後 cosine。
- 每個 epoch 把每張負樣本看一次，正樣本重抽到設定的比例。

預先登錄的設定（只有這三個，不再增加）：

| 名稱 | lr | 每個 batch 中正樣本的比例 |
|---|---|---|
| `base` | 0.005 | 0.5 |
| `lowlr` | 0.0025 | 0.5 |
| `negheavy` | 0.005 | 0.33 |

## 4. 在 dev 上選設定（事先寫定的規則）

候選必須同時滿足：

1. dev 的正樣本（95 張）判 present 的比例 ≥ `detector-v1` − 0.03。
2. 模擬開發畫面（`v3-dev` 的乾淨 RGB）：
   - 清楚可見的視角判 present 的比例 ≥ `detector-v1` − 0.01（v1：634 / 637）；
   - absent 場景的視角 false present = 0，absent blocked 不高於 v1 + 0.01。

滿足的候選中，選 dev 確認負樣本（245 張）false present@0.7 最低者；平手時選相似物件 false present 較低者。
都不滿足 → 不採用 `detector-v2`，照實記錄。

## 5. 正式評測（只跑一次）

- 真實照片：§2 的 test。v1 與 v2 都在正式評測時才第一次執行。
- 模擬：新的 namespace `detv2-sim`（`gen-nav-v1`，40 × 4 = 160 集，split `detv2-eval`）。
  - 本檔凍結後產生並 render。
  - v1 / v2 都在正式評測時才執行。
  - 加上完整 v3 管線（decision 025 凍結的元件）的 D0×P0 與 D1×L1。

| # | 判準 | 通過條件 |
|---|---|---|
| **T1（主要）** | test 確認負樣本的 false present@0.7（＝ A2） | ≤ 1%（與 R0a A2 相同，不放寬） |
| **T2（主要）** | test 正樣本不退步：<br>- 有框的 62 張：found@0.7，IoU ≥ 0.5；<br>- 影像層級的 72 張：present@0.7 | 各自 v2 − v1 ≥ −0.05（成對） |
| **T3（主要）** | 模擬：`detv2-sim` 清楚可見的視角判 present 的比例 | ≥ v1 − 0.01；absent 視角 false present = 0 |
| T4 | 完整 v3 管線換成 detector-v2（`detv2-sim`，D0×P0 與 D1×L1） | FA、FP、GR、全視角 GR、佔用看穿都是 0 |
| T5 | 只報告 | 下列各項，以及 v2 − v1 的成對差異與修好 / 弄壞的張數：<br>- A3（absent blocked）；<br>- 確認負樣本與相似物件各類的 false present；<br>- 正樣本的完全漏看（< 0.02） |

解讀（事先寫定）：

- T1–T3 都通過，才可以說：「困難負樣本微調在不犧牲召回的情況下，把真實偏難負樣本的誤報壓到 A2 的標準以內。」
  這仍然是**真實照片**的結論，不是實機。
- T1 未通過、但 v2 明顯降低誤報（T5 的成對差異）：報告實際降幅。zone 內的相似物件仍然是實機前的已知風險。
- T2 或 T3 未通過：不採用 v2，因為召回退步會讓 present 變成 inconclusive，模擬中的安全性雖然不受影響，但巡檢效率會下降。
- 任何結果都不修改 `tau_present` / `tau_absent`。

## 6. 不做的事

- 不調整門檻來配合 v2 的信心分佈。分佈改變只報告；重新校準是另一個版本。
- 不使用 test 選設定或停止訓練。
- 不用模擬影像訓練，避免模擬召回的檢查失去意義。
- 不換架構、不加類別、不使用付費服務。
- 訓練只在 RTX 5070 Ti 上進行，遵守共享 GPU lock；Mac 只跑 CPU 的 smoke test（幾個 iteration，確認程式可運作，不用於選擇）。
