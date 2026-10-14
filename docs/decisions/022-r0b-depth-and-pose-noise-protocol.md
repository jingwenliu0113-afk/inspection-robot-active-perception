# 022 — R0b：depth 雜訊與定位誤差下的 v2 安全性（模擬雜訊測試，預先登錄）

- **日期**：2026-10-14
- **狀態**：協定凍結；寫於任何 R0b 資料產生之前。結果以 decision 023 報告，正式資料只跑一次。
- **是否在看過正式結果後才新增 / 修改**：否。本檔在 R0a 執行期間起草、R0a 結果（decision 021）之後凍結，內容沒有因 R0a 結果改變：
  R0a 檢查真實影像上的 detector；R0b 檢查 depth 與位姿，主要安全指標與 detector 無關。
- 實作：`activeperception/r0b_noise.py`（誤差模型，`tests/test_r0b_noise.py` 檢查統計性質）、`activeperception/r0b.py`（條件與指標）。
- **這是模擬雜訊測試**（decision 020 §2）：Gazebo 影像加上依規格建模的誤差，不是真實感測器、不是實機驗證。

## 1. 問題

`decision-v2` 判 absent 的前提，是 64 個可能位置都被 depth「看穿」。物件所在的位置不可能被看穿，所以 detector 漏看也不會 false absent。
這個保證依賴兩件事：**depth 正確**與**相機位姿正確**。B0 已經看到，只用 AMCL 位姿（公分級誤差）時保證會失效，
decision 016 用「以 depth 對設施地圖精修位姿 + 看穿餘裕」修好了它，但那是在 Gazebo 的完美 depth 上。R0b 問：

- **Q1**：在模型化的真實 depth 誤差與定位 / 校正誤差下，v2 + decision 016 是否仍然不會 false absent？
- **Q2**：沒有 decision 016（直接用估計位姿）時，安全性在哪個誤差等級失效？
- **Q3**：代價：準確率與 `inconclusive` 增加多少？位姿精修在雜訊 depth 上的成功率？

## 2. 資料

- 場景：`gen-nav-v1`（Advanced B 的幾何：8 m 圍牆、柱子、2.0 m 視角環、1.1 m 桅桿相機），teleport render 初始視角 + 12 個候選，GT 來自語意標籤。
- 新 namespace、新 split（本檔 commit 之後才產生）：
  - `r0b-dev`（split `r0-dev`）：6 scene groups × 4 variants = 24 集，只用來檢查管線與雜訊實作，不調任何參數。
  - `r0b`（split `r0-eval`）：40 scene groups × 4 variants = 160 集，正式評估，只跑一次。
- detector：凍結的 `detector-v1`，在**乾淨的** RGB 上執行（R0b 只對 depth 與位姿加誤差）。

## 3. 誤差模型（`activeperception/r0b_noise.py`）

**Depth**（立體視覺 RGB-D；參考 TurtleBot 4 的 OAK-D Pro：4 m 內絕對誤差 < 2%，Luxonis 文件；RealSense D435：2 m 內 RMS ≤ 2%，Intel 規格）：

| 等級 | 隨機誤差（2 m 時，∝ z²） | 系統比例誤差 | 相關長度 | 不連續處 | 隨機缺值 |
|---|---|---|---|---|---|
| D0 | 0 | 0 | — | — | 0 |
| **D1（典型）** | 1%（2 cm） | +1%（高估距離） | 3 px | 2 px 內：一半缺值、一半 flying pixel | 1% |
| D2（規格上限） | 2%（4 cm） | +2% | 3 px | 3 px 內，同上 | 3% |

- 系統比例誤差一律取「高估距離」：這是會讓被擋住的視線看起來「被看穿」的方向（保守）。
- flying pixel 的值在鄰近前景與背景深度之間均勻抽樣；不連續門檻 0.10 m；最後量化到 mm。

**位姿**（相機的估計位姿 = 真實位姿 + 獨立高斯誤差，每個 (episode, 視角) 各抽一次）：

| 等級 | x、y | yaw | 高度 z | pitch | 依據 |
|---|---|---|---|---|---|
| P0 | 0 | 0 | 0 | 0 | — |
| **L1（典型）** | 3 cm | 0.02 rad | 1 cm | 0.005 rad | `nav-b0` 實測 AMCL 誤差（p95 7.6 cm / 0.039 rad）；桅桿校正誤差約 0.3° |
| L2（加倍） | 6 cm | 0.04 rad | 2 cm | 0.010 rad | 較差的真實定位與校正 |

- z、pitch 屬於校正誤差，2D 地圖精修**無法**修正；L2 的位置誤差有時會超出精修的搜尋範圍（±0.15 m、±0.08 rad），屆時精修會判為失敗並改用寬餘裕。
- 亂數：每個 (episode, 視角, depth 等級, 位姿等級) 一個固定的串流；兩條管線使用**相同**的抽樣，成對比較。

## 4. 條件與管線

3 個 depth 等級 × 3 個位姿等級 × 2 條管線 = 18 個條件。

- **(a) v2 直接用估計位姿**：Core 的 v2 觀測，位姿換成估計值（無精修、無餘裕）。
- **(b) v2 + decision 016**：凍結的 `nav-pose-v1`（以雜訊 depth 對設施地圖精修）＋ `nav-margin-v1`，與 Advanced B 相同。

四個方法（Single、Random seeds 0–2、Rule-NBV v2、Oracle v2）用 Core harness replay，budget 1–5；判定規則為凍結的 `decision-v2`。
所有凍結值（`decision-v2`、`rule-nbv-v2`、`detector-v1`、`nav-pose-v1`、`nav-margin-v1`）都不改。

## 5. 指標

| 指標 | 定義 | 與 detector 有關？ |
|---|---|---|
| **all-views geometric risk** | 物件存在的 episode，把 13 個視角全部聯集後 64 個位置都被看穿 | 否（最嚴格的幾何測試） |
| **occupied false clearance** | 物件存在時，距離物件中心 0.10 m 內的候選位置在某個視角被判為看穿（逐視角計數） | 否 |
| false absent | 判定為 absent 但物件存在（四個方法、budget 1–5） | 是（真實 detector） |
| geometric risk（策略選的視角） | 物件存在、但已選視角的聯集把 64 個位置都看穿 | 否 |
| 準確率、inconclusive rate | 四個方法、budget 2 / 3 | — |
| 精修成功率、精修後位姿誤差 | 管線 (b) | — |

D0 × P0 的 occupied false clearance 應為 0（在 `r0b-dev` 上檢查實作；若不為 0，先修正實作或「佔用位置」的定義，再凍結本檔附錄並產生正式資料）。

## 6. 預先登錄的判準

| # | 判準 | 通過條件 |
|---|---|---|
| **R1（主要）** | 管線 (b)、D1 × L1 | false absent 0、geometric risk 0（所有方法、所有 budget），all-views geometric risk 0 |
| R2（壓力） | 管線 (b)、D2 × L2 | 同 R1；報告通過或失敗 |
| R3（對照） | 管線 (a)、所有雜訊條件 | 只報告；預期在 L1 / L2 會失效（重現 B0 的發現） |
| R4（代價） | Rule 在 budget 2 / 3 的準確率、inconclusive rate；精修成功率 | 只報告 |

解讀（事先寫定）：

- R1 通過 → 「在模型化的典型 depth 雜訊與定位 / 校正誤差下，v2 + decision 016 仍不會 false absent」。這是**模擬**結論。
- R1 未通過 → v2 的安全保證在典型誤差下不成立。任何修正（例如更大的容忍值或餘裕）都是新版本，需要使用者決定，並以新資料驗證。
- R2 未通過但 R1 通過 → 記錄安全邊界的位置（哪個誤差等級開始失效）。
- 本檔不宣稱任何真實感測器、真實場地或實機的結果。

## 7. 不做的事

- 不調整任何凍結值以「通過」判準；不依 `r0b` 結果修改任何設定。
- 不模擬鏡面反射、黑色材質、陽光干擾、動態物體（超出範圍；記錄為限制）。
- 結果與 Core、Advanced B、R0a 分開報告，不合併。
