# Changelog

版本号按「功能变化」走，不按提交次数走。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

## [0.3.0] - 2026-11-10

知识树上线。这个 skill 从「能看一条视频」变成「能积累经验」。

### Added

- `knowledge/` 知识树，三层结构（facts / topics / conflicts / sources）+ 总索引
  - `DESIGN.md` 明确写了为什么不用单个大 MEMORY.md：单文件做不到"留痕"
  - `INDEX.md` 作为 agent 启动入口，含数据成熟度的诚实自评
- `knowledge/kb.py`，六个命令把设计变成可执行动作
  - `list` / `show` / `check` — 读与体检
  - `absorb` — 吸纳；值一致时追加来源并提置信度
  - `revise` — 修正；旧条 `superseded` 留痕，禁止直接覆盖
  - `conflict` — 冲突；相关 fact 标 `disputed`，置信度 ×0.6
  - `source` — 来源档案，含 `reliability` 与 `known_bias`
- `knowledge/topics/vbt.md` 首个主题归纳，把「推断」和「事实」分开
- `knowledge/conflicts/jerk_189_validity.yaml` 首个真实冲突案例：
  简介与画面判分牌结论相反，`unresolved` 挂着不强行和解
- `knowledge/sources/` 首个来源档案（Arcus VBT，reliability 0.6）
- `references/report-format.md` 从 5 条硬规则扩到 8 条

### Fixed

- `kb.py revise` 版本号算错：原按「来源数量」算代数，会生成不连续的 `.v5`。
  改为顺着 `supersedes` 链数，正确得到 `.v2`
- `kb.py source` 文件名截断隐患：sec_uid 前缀高度雷同（都是 `MS4wLjABAAAA`），
  截断到 60 字符会让不同博主撞同一个文件互相覆盖。改为超长时用「前缀 + sha1 前 8 位」

### Changed

- 抽帧默认参数回到 `--min-gap 0.25` / `--scan-fps 8.0`。
  曾因一次误判改成更高帧率，逐帧复核后确认原值是错的（见下方"教训"）

### 教训（写进文档，免得再犯）

- **"我没看到" ≠ "画面里没有"。** 曾看到抽帧里没有"举起"画面，断定算法漏了快速动作，
  改了帧预算和去重逻辑。用 20fps 逐帧复核 6.30–7.05 秒后发现：全程远景，
  选手只占很小一块，杠铃始终在腰以下 —— 画面上本来就没有。
  → 写进 `report-format.md` 第 7 条
- **联系表不能读数。** 把 1200px 联系表（每格 300px）上的一白一红读成两个白灯，
  把「上挺峰值速度」读成「平均速度」。缩略图丢的是小字、指示灯颜色、面板标签。
  → 写进 `report-format.md` 第 3.5 条 + SKILL.md 第三步警告

## [0.2.0] - 2026-11-09

打通「任意一条链接 → 整个博主的全部作品」，不需要登录。

### Added

- `scripts/douyin_author.py` 批量列博主作品，游客态可访问
  - `extract_sec_uid()` 支持三种输入：sec_uid 原文 / 主页 URL / 含 `/user/` 的任意文本
  - `--download` 时逐个调 `douyin_fetch.py`
- `meta.json` 补回 `author_sec_uid` / `author_uid` / `author_follower_count`，
  并在输出末尾直接打印「下一步可以批量看这个博主」的命令
- `scripts/make_sheet.py` 联系表生成，自动跳过 `outro` 帧并标时间戳
- SKILL.md 新增「需要登录吗」能力对照表，结论：**看内容不用登录，只有搜索需要**

### Fixed

- 抽帧双道去重：全局 0.97 拦"几乎一模一样" + 邻近 3 张/2 秒窗口 0.90 拦同段落近似帧。
  只保留其一都会出事（见 0.1.0 的坑三）
- 片尾帧判定改用正交信号：亮度相对全片中位数比值 `< 0.45`。
  实测 logo 帧两两 `norm_corr` 仅 0.57–0.81，而动作帧 0.84–0.93 —— **动作帧反而更像彼此**，
  任何能删 logo 的相似度阈值都会先误杀真动作

## [0.1.0] - 2026-11-08

从零建起来，核心是证明「不解析 HTML 也能拿到视频」。

### Added

- `scripts/douyin_fetch.py` 单条抓取
  - playwright 打开详情页，拦 `/aweme/v1/web/aweme/detail/` 响应
  - 视频 / 图文分流（`aweme_type == 68`、`images` 非空、`duration == 0`）
  - 短链 302 取 ID；失效短链明确报错不假装成功
  - 下载带 Referer，否则 CDN 403
- `scripts/sample_frames.py` 信息量驱动抽帧
  - 64px 灰度特征（宽高分别推导，不拉伸）
  - 与最近已保留帧比对，`norm_corr` 替代 SSIM（抵抗曝光变化）
  - 阈值自适应取 p90，不手填
- `references/douyin-tech-notes.md` 记录实测走不通的三条路
- `references/report-format.md` 观感报告格式

### 验证过的死路（别再试）

| 做法 | 结果 |
|------|------|
| 解析 `RENDER_DATA` | 207KB 全是配置和 AB 开关，零视频地址 |
| 直接请求 detail 接口 | 403，要 `a_bogus` 签名 |
| `iesdouyin.com/share/video/...` | SSR 只有空壳 |
| 监听 `context` 的 `request` 事件 | 永远收不到，必须挂 `page` 且 `goto` 之前 |
| 找独立字幕轨 | `is_subtitled: 0`，字幕烧在画面里 |
