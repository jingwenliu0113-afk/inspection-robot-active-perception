# NEXT

## 目前位置（2026-10-15）

**Core 結案（decision 014）＋ Advanced B 完成（decision 015–019）＋ 作品集整理 ＋ R0 完成（decision 020–023）
＋ v3 完成（decision 024–026）。A（detector 微調，decision 027）等 RTX；B（depth 模型檢查，decision 028）完成量測，D3 開發檢查中。**
不進 RL、不採購、不用付費服務（使用者 2026-10-15 再確認）。

### 需要 RTX 5070 Ti 的待辦（GPU 恢復後依序做）

1. `tools/detv2_gpu.sh check`：GPU 是否空閒、`/tmp/ai-portfolio-gpu.lock` 是否可取。被占用時就停，不搶鎖。
2. `tools/detv2_gpu.sh sync`：同步程式碼、train / dev 清單與影像到 gpu-server，約 350 MB，0.6 MB/s 約 10 分鐘。test 清單不會被複製。
3. `tools/detv2_gpu.sh train`：在 `flock -n` 下依序訓練 `base`、`lowlr`、`negheavy`。
4. `tools/detv2_gpu.sh fetch`：把權重和紀錄取回 `runs/detv2/<config>/`。
5. Mac 上：
   - `python -m activeperception.detv2.formal dev`：dev 真實照片與 `v3-dev` 模擬畫面，CPU；
   - 接著 `... formal select`：依 decision 027 §4 選設定。
6. 選到設定才做：`... formal test --out results/detv2`，只跑一次。它會：
   - 下載 test 影像，跑 v1 / v2；
   - 跑 `detv2-sim`（已封存、未執行）；
   - 判定 T1–T3。
   同一個指令也會跑 T4：完整 v3 管線改用 v2 的偵測，在 `detv2-sim` 的 D0×P0 與 D1×L1 上執行。
7. 寫結果 decision，更新 README 的 A 段落與 `tests/test_readme_claims.py`。

`tools/detv2_gpu.sh` 的遠端指令（ssh + wsl 引號、tar 串流）**今晚無法實測**，第一次使用時先跑 `check`。

### v3（decision 024–026）完成

| 項目 | 結果 |
|---|---|
| 開發 | 真實照片誤報分析、zone 過濾、幾何消融、矛盾處理（m6c）、平手處理（不採用）：[docs/v3-development.md](docs/v3-development.md) |
| 凍結 | decision 025（`b23b6c8`）；正式資料 `v3` / `v3-dx` 在凍結後產生（`3191947`） |
| 正式（decision 026） | **V1、V2、V3、V5 通過**；**V4（D2×L2）未通過**：1 / 1,040 個視角越過安全餘量（FA / GR 仍 0） |
| 主要數字 | D1×L1：Rule 0.787 / 0.956 / 1.000（v2 0.487 / 0.500 / 0.506）；zone 外消防栓 FP 1,014 / 1,263 → 0 |

### A：detector-v2（decision 027）

- 完成：
  - 協定（訓練前凍結）；
  - `data/detv2`（train 1,462 / dev 613 / test 871，test 從未執行）；
  - 影像下載，0 失敗；
  - 訓練、評測、正式 runner；
  - CPU smoke test；
  - 困難負樣本分析（[docs/detv2-development.md](docs/detv2-development.md)）；
  - `detv2-sim`（已封存）。
- 分析發現：真正困難的是人工確認的負樣本（v1 誤報 7–13%）；按類別挑的相似物件幾乎不誤報。

### B：depth 誤差模型檢查（decision 028）

- 資料：Rustler 2025 OSF 平面資料，D435 / D455，CC BY 4.0，186 MB，只存在本機 `data/raw/depthnoise/`。
- 依事先準則的結果：
  - 隨機誤差在 D2 範圍內，量化可忽略；
  - **D435 低估距離最多 2.48%**（模型只假設高估），相關長度長 2.6–3 倍；
  - D435 在 1 m 有固定樣式。
- D3 修正模型（`depthnoise/d3.py`）：開發檢查在 `runs/v3-dev/d3`。D3 的正式結論需要另寫 decision 與新資料（使用者決定）。
- 報告：[docs/depth-noise-check.md](docs/depth-noise-check.md)。

### R0（decision 020–）

| 步驟 | 狀態 |
|---|---|
| R0a 真實照片上的 detector（decision 020 協定 → 021 結果） | **完成**：A1 通過（clear 97.9%）、A2 未通過（偏難負樣本 false present 9.2%）、A3 不可用（47.8%） |
| R0b depth 雜訊 + 定位 / 校正誤差（模擬，decision 022 協定 → 023 結果） | **完成**：R1 / R2 通過（管線 b 在 9 種誤差組合都沒有 false absent）；但 depth 有雜訊時 absent 判不出（budget 5 下 0–1 / 80），精修位姿 p95 9–14 cm |

- R0a 資料：Open Images V7（影像只在本機 `data/raw/r0a/`；清單 `data/r0a/`）。train 框標註用排序檔的 Range 索引抓取（decision 020 附錄 A）。
- R0a 發現的結構弱點：判定取整張影像的最高信心，不檢查偵測框是否在 zone 內 → 修正屬新版本，需使用者決定（R0 範圍內不做）。
- 三種驗證不得混用：R0a = 真實照片、R0b = 模擬雜訊、實機 = 未做。
- R0b 的 dev 檢查修正了「佔用位置」半徑（0.10 → 0.06 m，decision 022 附錄 A，正式資料之前）。
- 下一步候選（都需使用者決定，見 `docs/roadmap-real-inspection.md`「R0 之後的建議」）：zone 內偵測 / detector 微調、depth 比例校正與精修品質檢查、處理缺值的看穿判定。
- R0a / R0b 都沒有用到 RTX 5070 Ti（CPU 即可）；若做 detector 微調（Advanced A）才需要取 GPU 鎖。

GitHub：https://github.com/jingwenliu0113-afk/inspection-robot-active-perception（private，不加 LICENSE）。每個 milestone commit 後 push。

| 階段 | 內容 | 狀態 |
|---|---|---|
| Core v1 / v2 / 結案 | decision 001–014 | 完成 |
| B0 | Nav2 + TB4 可行性；C6 未過 → decision 016（位姿精修 + 餘裕 + 停點重定位）→ `nav-b0d` 全部通過 | 完成 |
| B1 | 閉迴路整合（`nav-b1` 開發資料） | 完成（decision 017） |
| B2 | 正式評估 `nav-b2`（160 集、960 次閉迴路），Q1–Q4 全部成立 | **完成（decision 019、`results/nav-b2/`）** |
| 作品集整理 | README 改寫、架構圖、Demo、重現指南、Nav2 失敗分析、後續建議 | **完成**（不改任何封存結果或結論） |

### Advanced B 結論（decision 019）

- 安全：Nav2 下所有方法 false absent / false present / geometric risk 皆 0。
- Nav2 − teleport：四個方法皆不劣於 teleport（差 ≤ 0.006）。Rule budget 2：teleport 0.988 / Nav2 0.981。
- 主動視角仍有效：Rule − Random +0.079 [0.044, 0.119]（b2）、+0.017 [0.004, 0.033]（b3）；Rule 每集少走 0.46 m。
- 導航 440 次全部準確到點、碰撞 0、逾時 0。啟動看門狗重試 20 次（全部恢復）。
- 限制：只在模擬中（理想里程計、已知起點與設施地圖、固定場景幾何）；與 Core 數字不可直接比較。

## 主要結果

- v1 原 test（524 ep）：Rule 0.706 / 0.996（budget 2 / 3），Random 0.620 / 0.907；Oracle − Rule 0.004。
- holdout（600 ep）v1：Rule 0.683 / 0.968，Random 0.608 / 0.898；**Oracle − Rule 0.028 / 0.032 → 原 test 的「接近 Oracle」未重現**。
- holdout v2：Rule **0.957 / 0.998**，Random 0.868 / 0.975，Single 0.392，Oracle 1.0 / 1.0；所有方法 false-absent = 0；ECE ≤ 0.008。
- **v2 的改善主要來自 absent 判定規則，不是 NBV 策略**：判定規則 +0.253（修好 152、弄壞 0）；策略 +0.020 [−0.020, 0.058]（修好 31、弄壞 19，不顯著）。
- Gate 未通過：v1 Gate 4 在 holdout；v2 Gate 4 在 budget 2（Oracle − Rule 0.043 [0.020, 0.070]）。
- failure analysis：v1 budget 2 失敗約 90% 是結構性（Oracle 也失敗）；v2 殘餘失敗 100% 可歸因於視角選擇；
  rule-nbv-v2 在初始視角被擋時 75–81% 的第二視角決策是平手、按候選編號選（開發資料）。

## 待使用者決定

1. **下一步方向**（[docs/roadmap-real-inspection.md](docs/roadmap-real-inspection.md)，尚未啟動）：
   - R0a 真實影像的 detector 檢查、R0b depth 雜訊下 v2 的安全性（兩者不需採購，建議先做）；
   - R0c 方法修正（rule-nbv-v2 平手、到點容忍值）；R1 之後需要採購硬體。
   - 使用者已決定：暫不購買實體機器人、不做 Advanced C。
2. 任何新版本都需要新的 namespace 與未參與開發的資料；`core` test、`holdout`、`nav-b2` 都已使用過。

## 作品集整理（2026-10-14）完成的事

- README 改寫：重點結果、**驗證範圍（模擬已驗證 / 實機未驗證）**、Demo、架構圖、研究紀律、重現；原有結果、Gate、未通過項目全部保留。
- `docs/architecture.md`（Mermaid 圖、資訊邊界、模組對照）、`docs/reproduce.md`（四個層級）、`docs/roadmap-real-inspection.md`。
- Demo：`docker/demo.sh`（一集 nav-b1 Nav2 閉迴路，約 1–1.5 分鐘）＋ `tools/make_demo.py`（GIF / 分鏡，重建判定輸入並與 `run.json` 比對）。
- 失敗分析 Part B：`activeperception/nav/failure_analysis.py` → `results/nav-failure-analysis/summary.json`（事後、唯讀）；
  新發現：起點位姿精修在 3 / 40 個場景一律退化（72 / 960 次起點拍攝），decision 019 的「精修失敗 5 / 440」只算停點；
  停點重定位 92.5% 用滿 2 次修正，最終朝向誤差中位 0.046 rad 貼近 0.05 容忍值。
- 新圖：`nav_b0_lineage.png`、`nav_cost.png`、`demo_nav2_*`、`failure_nav2_margin.*`；既有圖逐位元未變。
- 重新確認：spec 全部逐位元重新產生；封存的 test / holdout 以 `--reproduce` 逐位元相同。
- 測試 188（新增 `test_nav_failure_analysis.py`、`test_readme_claims.py`：README 主要數字必須等於已 commit 的結果）。
- Nav2 重跑不是逐位元可重現：`nav-b1-g0001-v3` 原本 3 個視角，Demo 重跑 4 個（判定相同）。

## 已驗證的事實（不要重做）

- Gazebo depth 是 **planar depth**（與 ray-cast 比對：中位誤差 0.25 mm、p99 0.5 mm），非物件像素 label 一致 99.98%。
- 同 pose 重 render、跨 server、10 Hz vs 30 Hz：RGB / depth / labels **逐像素相同**。
- Python gz bindings 不可訂閱 `/world/<w>/clock`（約 250 Hz，會讓服務請求逾時並在結束時 segfault）。
- `remove/blocking` 在平行容器下偶爾回 false → clear pass 改用 `set_pose_vector` 停放柱子（與移除逐像素相同）。
- detsel 上三個 detector 主指標飽和（AUROC 1.0），由授權 tie-break 選 FRCNN（decision 005 附錄 B）。
- FRCNN 在 Mac CPU / MPS 與 CUDA 的最高 confidence 差 ≤ 5e-4（容器 CPU ≤ 0.004）。
- replay world 必須 memoize 觀測，否則調參每次 run 都重讀 npz（6 ms → 25 µs）。

## Blocked / 注意事項

- **跨專案**：`rtu-maintenance-platform` 的流程在停掉自己的 DB 容器後會關閉 Docker Desktop（2026-10-13 11:33、15:01、16:01，看起來每小時一次；supervisor log 可見）。
  本專案 render 會被中斷，但可續跑（已完成的 episode 自動跳過，單一 episode 失敗會重試）。本專案只重新啟動 Docker Desktop，從不碰其他專案的容器。
- Mac 從 GitHub release 下載大檔不穩（兩次截斷）；權重一律以官方 digest 驗證，必要時從 gpu-server 串流回來。
- Mac ↔ gpu-server 傳輸約 0.6 MB/s（760 MB 約 21 分鐘）。
- gpu-server：`~/ai-portfolio/inspection-robot-active-perception`，`.venv-det`（torch 2.13.0+cu130，全部由 uv 快取離線安裝），不動 Ubuntu-22.04 系統環境。

## 已知 SPEC 差異

- SPEC §2 `visible` 寫「初始/可達視角可觀測」；實作採「初始視角」定義，「可達」另記為 `revealable`（decision 002）。core 中 revealable 皆為真（沒有「所有候選都看不到」的 present episode）。
- SPEC §3 寫 Nav2 放 Advanced：維持。ROS 2 在 Core 只做 teleport 與系統整合（decision 001 附錄 B / D）。

## 本 session 完成的事（2026-10-13，含 v2 與 Core 結案）

- M2–M5 全部：Docker 映像與 smoke test、decision 005–010、gen-v2 消防栓 world、render-then-replay、depth / label sensing、
  detector 選型（RTX 5070 Ti、GPU lock）、pilot 六項 + ROS 2 線上一致性、core 1200 ep、調參、凍結、正式 test、Gate 判定、README 結果與圖。
- GitHub private repo 建立並 push。
- v2：decision 011（設計 / 資料 / 協定）、附錄 A（train 上修正位置密度）、012（凍結）、013（holdout 結果）；
  `decision-v2`、`rule-nbv-v2`、`oracle-v2`、`frozen_v2`、`experiment_v2`、v2 tests、v1 回歸測試（val 數字逐位元重現）。
- holdout 渲染、GPU 偵測、一次性比較；README 新增 v2 段落與圖（v1 段落數字未改）。
- Advanced B0：decision 015（協定 + 附錄 A 整合調整 + 附錄 B 結果）、`Dockerfile.nav`、`activeperception/nav/`、`docker/nav_smoke.sh` / `nav_b0.sh`、`tests/test_nav_b0.py`、`results/nav-b0/`。
- Core 結案：decision 014；`failure_analysis.py`（只讀已 commit 結果 + 開發資料平手分析）、`docs/failure-analysis.md`、`failure_attribution.png`；
  `seal.py` + `SEALED.sha256` + `tests/test_seal.py`（正式 runner 對封存資料只允許 `--reproduce`）；Advanced B 評估（唯讀容器檢查 Nav2 套件）。
