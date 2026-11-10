# Changelog

版本号按「功能变化」走，不按提交次数走。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

## [0.5.1] - 2026-11-10

### Fixed

- `kb.py absorb`：给已有 fact **只追加来源、不带 `value`** 时被误判为「值不一致」并拦下。
  这是最常见的用法（新视频印证了老结论），实际上完全跑不通。
  根因是 `str(None) != str(旧值)` 的硬比较。改为先判 `has_value`，
  无 value 直接走合并；同时抽出内部 `_merge()`，消掉三个分支各写一遍的落盘代码。
  回归：追加第二来源 → `+1 来源 → conf 0.7`；重复同一来源 → 「来源已存在，未变」；
  故意错值 → 仍正确报冲突且未写库。

### Knowledge

- 新增 `barbell.desc_has_power_not_on_panel`（conf 0.5 → 0.7，2 个来源）：
  简介与画面**不是包含关系**。Peak V 两处都有且一致（1.99 互相印证）；
  Mean V / 平均功率 / 峰值功率只存在于简介文字里，画面上读不到、无法复核。

## [0.5.0] - 2026-11-10

**为换机器执行做准备。** 这一版几乎没加新功能，全是「让另一台机器上的 agent
读完文件就能接手」的工程改动。

### Added

- **`HANDOFF.md`** —— 接手说明。前因后果、四条坑、当前进度、下一步任务，
  30 秒版本在最前面。**换机器第一份要读的就是它。**
- **`PLAN.md`** —— 刷视频计划。三阶段（换领域验通用性 / 补纵向数据 / 找失败样本），
  含每批 11 项执行清单和"这轮算成功吗"的判据。
- **`scripts/setup_env.py`** —— 环境自检与一键安装。
  `--check` 只体检，不带参数则缺什么装什么。
  检查 python / playwright / chromium / numpy / Pillow / requests / pyyaml / ffmpeg。
- **`scripts/ffmpeg_locator.py`** —— 共享的 ffmpeg 定位，
  按 `FFMPEG_BIN` → PATH → `imageio-ffmpeg` → Windows 通用位置 顺序查找。
- **`requirements.txt`** —— 依赖清单，含镜像安装说明。
- fact `barbell.desc_has_power_not_on_panel`：简介与画面**不是包含关系**。
  Peak V 两处一致可互校，但 Mean V 和功率只在简介里，画面无法复核。

### Changed

- **SKILL.md 开头加「第一次用？按这个顺序读」表格**，明确六份文档的阅读顺序。
- 「环境依赖」整节重写，**去掉了所有本机路径**，改为指向 `setup_env.py`。
- `references/douyin-tech-notes.md` 的环境基线表改用相对路径描述，
  并注明「换机器不要照抄路径，跑 setup_env 拿真实状态」。
- 文档里写明 `sample_frames.py` 输出会多一层 `frames/` **是既有约定不是 bug**。

### Removed

- 三处硬编码的 `C:\Users\04kt-13\WorkBuddy\2026-09-22-...\ffmpeg.exe`。
  `douyin_fetch.py` 和 `sample_frames.py` 各有一份 `find_ffmpeg`，
  两份都写死了上一台机器的工程目录 —— 换机器后两处同时失效、报错还不一样。
  现在合并成一个模块。

### 验证

在干净目录里复制整个 skill 后实测：

| 项 | 结果 |
|---|---|
| `setup_env.py --check` | 🟢 全部就绪，exit=0 |
| `kb.py check`（系统 python / venv 都试过） | 20 facts，problems 为空 |
| 四个脚本 `--help` | 全部 OK |
| **真实抓取一条视频** | 成功，1.41 MB，`author_sec_uid` 正常输出 |

## [0.4.0] - 2026-11-10

第一次用知识树自由浏览：14 条视频 → 19 条 fact，两处结论被推翻并留痕。

### Added

- 知识树从 7 条扩到 **19 条 fact**（4 个主题文件：`vbt` 15 条、`barbell` 4 条）
- `topics/barbell.md` 新建，专放跨动作规律
- `conflicts/snatch_weight_184_vs_188.yaml` 第二个真实冲突：
  简介 188kg / 大屏 184kg，差 4kg，`unresolved`
- 深蹲衰减 4 组新样本（170kg×5、165kg×3、150kg×2、140kg×4、130kg×5 低杠），
  幅度覆盖 10%–53%
- 单次举重 Peak V 与 ROM 四条（垫上抓举 2.08/75.3、抓举 1.99/96.3、
  分腿挺 1.75/52.5、高翻 1.72/100.4）
- 面板能力三条：ROM 逐次记录、关节角度叠加、**侧边 m/s 是瞬时值不是成绩**

### Changed

- 来源 `reliability` 0.6 → 0.65：面板内部数据自洽（速度/ROM/损失能互相验算），
  但简介出过错、样本选择性明显、文案模板化
- `topics/vbt.md` 全文重写，加了「边界与失效条件」，撤回上一轮关于
  「可用衰减判断该不该加组」的猜测

### Fixed

- `kb.py revise` 新 id 生成错误：`args.fact_id.split(".v")[0]` 对不含 `.v` 的 id
  会切在第一个 `.` 上，把 `barbell.velocity_by_lift_type` 砍成 `barbell`，
  生成出 `barbell.v2` 这种丢主体的名字。改为正则去尾部 `.vN`
- `kb.py source` 文件名截断隐患：sec_uid 前缀高度雷同（都是 `MS4wLjABAAAA`），
  截到 60 字符会让不同博主撞同一文件互相覆盖。改为超长时「前缀 + sha1 前 8 位」
- 上一轮测试残留的占位 sec_uid 已清除，来源档案改用真实 sec_uid

### 教训（写进文档，免得再犯）

- **联系表读数错误，同一条错误犯了第二次。** 在 711KB 的联系表（14 格）上，
  把「140kg 4/4 速度损失 10%」读成「160kg 5/5 速度损失 33%」，
  还据此准备判定「简介与面板矛盾」。回原帧才发现：那条视频**全程 140kg**，
  简介说的 10% 完全正确 —— 差点冤枉博主。
  → 已在 INDEX.md 写入口径第 4 条点名这次错误
- **瞬时速度 ≠ 该次成绩。** 面板侧边 m/s 在 5.88s 显示 0.66、6.12s 显示 0.70，
  是同一个第 1 次动作过程中的跳变。误当成绩会得出完全不存在的"速度序列"。
- **衰减不是单调的。** 140kg×4 的第 3 次（0.47）比第 2 次（0.40）高。
  上一轮「单调下降」的说法只对 235kg 那一组成立。

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
