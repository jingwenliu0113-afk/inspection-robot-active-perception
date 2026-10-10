# Inspection Robot + Active Perception SPEC

## 一句話問題

在物件可能「可見、被遮擋、根本不存在」的 inspection task 中，active perception 能不能在固定觀測預算下，比單一視角與隨機移動更可靠地判斷 `present / absent / inconclusive`？

## 研究核心

這題不是先做一台完整自主巡檢機器人，而是把三個問題拆開：

1. 單一視角看不到物件時，系統能不能避免把「看不到」誤判成「不存在」？
2. 下一個 viewpoint 的選擇是否真的提高可觀測性與最終判斷品質？
3. 在相同 viewpoint budget 下，rule-based active perception 是否勝過 single-view 與 random baseline？

---

# Core

## 1. 固定模擬平台

目標版本：

- ROS 2 Jazzy
- Gazebo Harmonic

正式實驗前記錄：

- OS / ROS / Gazebo 版本
- world / model revision
- sensor config
- camera intrinsics / extrinsics
- random seed
- object / occluder placement generator version

## 2. 三種真實狀態

每個 episode 的 ground truth 必須明確屬於：

- `visible`：目標存在且初始/可達視角可觀測
- `unobservable`：目標存在，但初始視角被遮擋或不足以可靠判斷
- `absent`：目標不存在

系統輸出只能是：

- `present`
- `absent`
- `inconclusive`

Core 不允許把「沒有偵測到」直接等同 `absent`。

## 3. 先隔離 perception 與 navigation

Core 使用 teleport 或 deterministic pose placement 到候選 viewpoint。

目的：

- 不讓 Nav2 failure 混入 perception / viewpoint policy 的因果分析。
- 保證不同方法使用相同候選 viewpoint 與 budget。

Nav2 放到 Advanced。

## 4. Frozen Episode Set

episode generator 至少控制：

- object present / absent
- occluder layout
- lighting / texture（若使用）
- initial viewpoint
- candidate viewpoints
- seed

train / validation / test 以 scene seed 或 scene group 為最小切分單位，不得讓同一場景的輕微變體跨 split。

## 5. Baselines

Core 至少比較：

1. **Single View**：只看初始視角。
2. **Random NBV**：在候選 viewpoint 中隨機選下一視角。
3. **Rule-based NBV**：只用部署時可取得的 observation-derived features 選視角。
4. **Oracle NBV**：只作 upper bound；可使用 simulator ground truth，但不得作為正式 deployable method。

所有方法使用相同最大 viewpoint budget。

## 6. Rule-based NBV 可用資訊

可以使用：

- detector confidence / uncertainty
- bounding-box area / pixel area
- observation history
- viewpoint geometry 本身
- 已看過區域或視角的 coverage proxy

不得使用：

- object GT pose
- object GT visibility
- occlusion GT
- simulator semantic truth
- 未來 viewpoint 的真實 detector outcome

## 7. 指標

至少報：

- 3-class accuracy / macro-F1 (`present/absent/inconclusive`)
- false absent rate（目標其實存在卻判 absent）
- inconclusive rate
- average viewpoints used
- success vs viewpoint budget curve
- calibration（confidence / reliability curve 或 ECE）
- visible / unobservable / absent 分層結果

若 detector 有 bounding box：另報 pixel-area / confidence 與成功率關係。

## 8. Budget

正式比較至少固定 3 組 viewpoint budget，例如：

- 1 view
- 3 views
- 5 views

實際值在 pilot 後、正式 test 前凍結。

## 9. Pilot

先用小型 pilot 驗證：

- 三種狀態真的可區分
- teleport viewpoint deterministic
- sensor timestamp / transform 正常
- single / random / rule / oracle 都吃到相同候選 viewpoint
- `inconclusive` 不會被 grader 當錯誤偷吃掉

Pilot episode 不進 final test。

## 10. Core Gate

只有在以下條件成立時才考慮 Advanced：

- Rule-based NBV 在 held-out test、相同 budget 下穩定勝過 Random 與 Single View。
- 差異不是來自 candidate viewpoint leakage。
- 仍存在明確、可重現的殘餘失敗。

若 rule-based 已接近 oracle，停止，不需要 RL。

---

# Advanced

## A. Detector Fine-tuning

只有當 Core 顯示主要瓶頸是 perception 而非 viewpoint choice 時才做。

比較 fine-tune 前後：

- recall / precision
- calibration
- false absent
- active perception 最終成功率

## B. Nav2 Integration

把 teleport 換成實際 navigation。

新增：

- path success
- navigation latency
- collision / timeout
- reachable viewpoint rate

必須保留 teleport 結果，才能區分 navigation failure 與 active perception failure。

## C. RL for Next-Best-View

只有當：

- rule-based NBV 明顯落後 oracle，且
- gap 可歸因於 sequential viewpoint policy，而非 detector / navigation

才允許做 RL。

RL 必須和相同 budget 的 Random / Rule / Oracle 比較。

---

# Optional

- 真實相機 / 實體機器人驗證
- SLAM / map uncertainty
- 多物件 inspection
- domain randomization
- sim-to-real

---

# 不做什麼

- Core 不做完整 autonomous robot stack。
- Core 不做 SLAM 研究。
- Core 不做 RL。
- 不把「看不到」等同「不存在」。
- 不用 GT 幫 deployable policy 選 viewpoint。
- 不追求漂亮 demo 而犧牲可控實驗。

---

# GitHub 最終成果

README 首屏建議包含：

- 三狀態任務圖（visible / unobservable / absent）
- Single vs Random vs Rule vs Oracle 表格
- success vs viewpoint budget curve
- false-absent 分析
- 失敗案例影片 / GIF

若進 Advanced，再加：

- teleport vs Nav2 差距
- rule vs RL vs oracle frontier
