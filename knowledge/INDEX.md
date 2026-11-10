# 知识树索引

> 给 agent 启动时读的极简入口。细节去 `facts/` `topics/` `conflicts/` `sources/` 里找。
> 最近更新：2026-11-10（共看过 14 条视频）
>
> **接手这个知识树的人，先读 `../HANDOFF.md` 和 `../PLAN.md`。**

## 现在有哪些主题

| 主题 | facts | 状态 | 一句话 |
|---|---|---|---|
| `vbt` | 15 条（12 active / 2 disputed / 3 superseded） | 有骨架 | 举重用杠铃速度判疲劳；深蹲衰减 5 组样本，幅度 10%–53% |
| `barbell` | 5 条（4 active / 1 disputed / 1 superseded） | 起步 | 四种动作的 Peak V 与 ROM；ROM 与速度不成正比 |

合计 **20 条 fact**，2 个未解冲突，1 个来源档案。

## 必须先知道的冲突

1. **`jerk_189_validity`**（unresolved）—— 挺举 189kg：简介说判无效，
   画面判分牌 GOOD LIFT + 一白一红。**两层证据都在，不和解。**
   受影响：`vbt.jerk_peak_v_189kg`（disputed，0.3）。

2. **`snatch_weight_184_vs_188`**（unresolved）—— 土库曼斯坦选手抓举：
   简介 188kg、大屏 184kg，差 4kg。**引用时必须两个都写。**
   受影响：`barbell.desc_weight_mismatch_184`（disputed，0.3）。

## 来源可信度

| 博主 | reliability | 主要偏差 |
|---|---|---|
| Arcus VBT | 0.65 | 只发成功镜头；简介有数字错（188 vs 184）；文案高度模板化 |

## 两条最容易踩的坑（已写进 fact）

- **`vbt.panel_speed_index_is_instantaneous`** —— 面板侧边那个 m/s 是**实时瞬时速度**，
  会随动作阶段跳变，还会标「离心/向心」。**不是该次成绩。**
  要逐次速度，必须看「逐次平均速度」列表或汇总卡。
- **`barbell.velocity_by_lift_type.v2`** —— 深蹲报 **Mean V**、举重报 **Peak V**，
  量级差 4–5 倍主要是**口径差**，不是动作差。跨动作比速度 = 错的。
- **`barbell.desc_has_power_not_on_panel`** —— 简介和画面**不是包含关系**，
  各有独占信息：Peak V 两边都有且一致；但 Mean V、平均/峰值功率**只在简介里**，
  画面上读不到、也无法复核。

## 数据成熟度（诚实版）

比上一轮厚了，但**关键空洞还在**：

- 深蹲衰减有 5 组样本（235/170/165/150/140kg），能看出幅度差异很大（10%–53%）
- **但没有任何一组是「同一人事、同重量、跨训练日」** —— 这是判断
  「衰减百分比有没有诊断价值」的唯一材料，目前为零
- **没有任何失败组画面** —— 这个号只发成功镜头，所以「衰减到多少会失败」无数据
- 单次举重每个动作只有 1–2 个样本，任何"规律"都立不住

## 本轮修正了什么（留痕在哪）

| 上一轮的说法 | 现在 | 原因 |
|---|---|---|
| 「235kg 衰减 34%，属明显疲劳信号」 | `vbt.squat_velocity_decay_235kg.v3`：幅度 10%–53% 大幅波动且可非单调，不能只看首末比 | 新拿 4 组数据，34% 落在中段 |
| 「深蹲比抓举慢 4-5 倍」 | `barbell.velocity_by_lift_type.v2`：是 Mean/Peak 口径差，不可比 | 面板口径不同 |

## 常用命令

```bash
cd knowledge
python kb.py list                     # 列全部 fact
python kb.py list --topic vbt         # 按主题
python kb.py show <fact_id>           # 看一条的完整来源链
python kb.py check                    # 体检：悬空引用、无来源
```

## 写入口径（别违反）

1. 一条 fact 只写一个可独立验证的断言，必须带 `sources`（`aweme_id` + 画面 `t`）
2. 推翻旧结论走 `revise`，旧条留痕变 `superseded`，不许直接删改
3. 两个来源打架走 `conflict`，`unresolved` 是合法长期状态
4. **画面里读到的数字必须回原帧确认，联系表上的读数不算**
   —— 本轮又在 711KB 的大联系表上把「140kg 4/4 损失 10%」读成「160kg 5/5 损失 33%」，
   回原帧才发现。同一条错误犯第二次了。
5. 推断和事实分开写 —— `topics/` 里可以推，`facts/` 里只放能指到某一帧的东西
6. **不要把 Mean V 和 Peak V 放同一列比高低**
