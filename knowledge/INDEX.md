# 知识树索引

> 给 agent 启动时读的极简入口。细节去 `facts/` `topics/` `conflicts/` `sources/` 里找。
> 生成时间：2026-11-10

## 现在有哪些主题

| 主题 | facts | 状态 | 一句话 |
|---|---|---|---|
| `vbt` | 6 条（5 active / 1 disputed） | 起步 | 举重用杠铃速度判断疲劳，已有 235kg 蹲的衰减曲线 |

## 必须先知道的冲突

- **`jerk_189_validity`**（unresolved）—— 挺举 189kg：简介的措辞指向没成，
  画面判分牌却是 GOOD LIFT + 一白一红。**两层证据都在，不强行和解。**
  凡是"这一把成没成"的问题，答案取决于你站在哪一层上。
  受影响的 fact：`vbt.jerk_peak_v_189kg`（已标 disputed，置信度压到 0.3）。

## 来源可信度

| 博主 | reliability | 主要偏差 |
|---|---|---|
| Arcus VBT | 0.6 | 只发成功/接近达标的试举；设备是自家产品，带营销色彩 |

## 数据成熟度（诚实版）

**这套知识目前还很薄。** 全部内容来自同一个博主的 4 条视频，7 条 fact，
其中真正能拿来做判断的只有「235kg 蹲速度衰减 34%」这一条。
抓举 91/92kg 两个数**不能**拼成速度—重量曲线 —— 是两个人、两个重量、各一次。

不同运动员、同一重量、多次试举的数据 = 零。这是最大的空洞。

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
4. 画面里读到的数字必须回原帧确认，联系表上的读数不算
5. 推断和事实分开写 —— `topics/` 里可以推，`facts/` 里只放能指到某一帧的东西
