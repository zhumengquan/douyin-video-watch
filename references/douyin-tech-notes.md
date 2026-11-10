# 抖音技术路线实测记录

> 这里记的是**实测得到的事实**，不是猜测。每条都标了怎么验证的。
> 抖音前端改动频繁，如果本文件里的结论与实测不符，以实测为准，并回来更新本文档。

## 环境基线（2026-11-10 实测）

> ⚠️ 下表是**首次实测那台机器**的环境，具体路径仅供参照。
> **换机器后不要照抄路径**，跑 `python scripts/setup_env.py --check` 拿当前机器的真实状态。

| 项目 | 第一次实测时的状态 |
|------|------|
| Chromium (playwright) | `%LOCALAPPDATA%\ms-playwright\chromium-1254`（158.0.8127.18） |
| Edge | `%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe` |
| ffmpeg / ffprobe | 从 PATH 找到（也可设 `FFMPEG_BIN`，或 pip 装 imageio-ffmpeg 兜底） |
| Python | 需 playwright + numpy + Pillow + requests + pyyaml |

**ffmpeg 定位已统一**到 `scripts/ffmpeg_locator.py`，不再硬编码任何路径。

### 装依赖的坑

**pip 直连 pypi.org 会卡死。** 实测：`urllib` 直连 pypi 1.3 秒通，但
`pip install playwright` 跑了 4 分多钟毫无进展。加腾讯镜像 10 秒装完。

```bash
python -m pip install --no-cache-dir \
  -i https://mirrors.tencent.com/pypi/simple/ \
  --trusted-host mirrors.tencent.com playwright requests
```

```bash
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
  python -m playwright install chromium
```

## 完整链路（已验证可用）

```
分享文案
  │  extract_input() 抠 URL
  ▼
v.douyin.com/<code>/
  │  不带重定向请求，从 302 的 Location 取视频 ID
  ▼
www.douyin.com/video/<id>
  │  playwright 打开，拦 /aweme/v1/web/aweme/detail/
  ▼
aweme_detail JSON（200，约 40KB）
  │  parse_aweme() 判断视频/图文
  ▼
video.mp4  或  images/
  │  sample_frames.py 抽关键帧（含 outro 标记）
  ▼
frames/ + frames.json
  │  make_sheet.py 拼联系表（自动跳过 outro）
  ▼
sheet.jpg → agent 一次看完 → 观感报告
```

## 四条死路（实测确认，别再试）

### 1. `RENDER_DATA` 里没有视频地址

实测首页与视频页都试过，`RENDER_DATA` 解出来 **207,579 字节**，
顶层只有 `app` 键，内容全是 `tccConfig`（下载链接、footer、AB 配置）
和 `abTestData`（播放器开关）。**零视频地址。**

### 2. 裸请求 `/aweme/v1/web/aweme/detail/` 返回 403

这个接口要 `a_bogus` 签名。自己造签名是纯消耗战，抖音一改就废。

**正确做法：让页面自己发、自己签，我们在旁边拦响应。**

### 3. 分享页 SSR 只有壳

`www.iesdouyin.com/share/video/<id>/` 返回 200（约 32KB），
带 `window._ROUTER_DATA`，但 loaderData 里只有 ua/query 这类壳，无 `play_addr`。
无头打开直接显示「抱歉出错了 请尝试在抖音内观看」。

### 4. `--dump-dom` 拿到 0 个视频流

实测 Edge `--headless=new --dump-dom` 拿到 1.42 MB DOM，
里面有 `<video>` 标签、有 `playAddr`（6 处）、有 `url_list`（4 处），
但：

- `playAddr` 全是 **配乐 mp3**（`ies-music/<id>.mp3`）
- `douyinvod` 只出现在 `<link rel="dns-prefetch">` 里
- `video/tos` 出现 **0 次**

**为什么 music 也有 `play_addr`** —— 音乐和视频共用这个字段名。
全 JSON 递归找 `play_addr` 会捞到 mp3，是最常见的误判。

## 关键实现细节（踩过才知道）

### 监听必须挂在 page 上

```python
page = await ctx.new_page()
page.on("request", on_req)          # ← 必须在 new_page 之后、goto 之前
page.on("response", on_resp)
await page.goto(url, ...)
```

实测挂在 `context` 上报 `request` 事件，**永远是 0 条**。
挂在 page 上立刻能看到 3 条 aweme 请求，6 秒内 detail 响应到达 3 次。

### 等 detail 响应要主动轮询

一次 `wait_for_timeout(9000)` 也可以，但更稳的是每秒检查一次：

```python
waited = 0
while waited < timeout_s * 1000 and not caught:
    await page.wait_for_timeout(1000)
    waited += 1000
```

### 下载必须带 Referer

```python
cmd = [ffmpeg, "-v", "error", "-y",
       "-headers", "Referer: https://www.douyin.com/\r\n",
       "-user_agent", UA,
       "-i", url, "-c", "copy", out_path]
```

不带 Referer 会 403。`-headers` 的值要带 `\r\n`。

### 短链会失效

实测两个历史链接：

| 链接 | 状态 |
|------|------|
| `v.douyin.com/YxucCuqGzCs/` | **已失效**，302 直接跳 `www.douyin.com` 主页 |
| `v.douyin.com/-Xzw-Dp9Xtc/` | 有效，解析到 ID `7700635904671674851` |

**失效的表现是 302 到主页，不是报错。** 必须显式识别，否则会拿主页当成功。
脚本已处理：Location 去掉尾部斜杠等于 `https://www.douyin.com` 就判失效。

## 内容类型判断（这一步不能省）

实测同一条链接 `7700635904671674851`：

| 字段 | 值 | 含义 |
|------|-----|------|
| `aweme_type` | **68** | 图文作品 |
| `media_type` | **2** | 图文 |
| `images` | 6 张 | 有图 |
| `video.duration` | **0** | 没有视频时长 |
| `video.bit_rate` | **空** | 没有码率档位 |
| `is_subtitled` | **0** | 没字幕 |
| `caption` | `""` | 空 |

图文作品的 `video` 节点是**残缺的**，`play_addr` 里塞的是配乐 mp3。
如果先不判类型直接找视频流，会一直找不到，误以为方案失败。

**判断公式**：
```python
is_image_post = bool(images) and (video.get("duration") or 0) == 0
# 或者 aweme_type == 68 / media_type == 2
```

### 同一作者的作品类型对比

用作者页 `www.douyin.com/user/<sec_uid>` 拦 `/aweme/post/` 拿到 21 条：

| 类型 | 数量 | `aweme_type` | `media_type` | `bit_rate` 档数 |
|------|------|--------------|--------------|-----------------|
| 图文 | 2 | 68 | 2 | 0 |
| 视频 | 19 | 0 | 4 | 6-8 档 |

**视频作品的 `bit_rate` 是完整的**，每档都有 `play_addr.url_list`。

## 字幕：确认拿不到

实测三条字段全空：`is_subtitled: 0`、`video_text: []`、`caption: ""`。
`caption_infos` / `captionInfo` / `subtitle_infos` / `cla_info` 在 JSON 里**一次都没出现**。

**结论：抖音字幕是烧进画面的，不是独立轨道。**
想读文字只能靠看画面，或者从 `desc`（标题简介）里取。

## 抽帧算法标定

`sample_frames.py` 参数全部来自实测。

### 帧间差异分布

64px 特征扫描，三条视频的帧间平均绝对差：

| 分位 | 深蹲 23s (4fps) | 深蹲 23s (8fps) | 抓举 13.7s (8fps) |
|------|----------------|----------------|-------------------|
| p25 | — | — | 6.78 |
| p50 | — | — | 13.19 |
| p80 | 11.62* | — | 25.63 |
| p90 | 22.93 | — | 34.24 |
| p95 | 35.01* | — | 46.11 |
| max | 70.33* | — | 68.20 |

\* 早期 4fps 扫描、旧两条视频的数据，保留用于对照。

**注意 p50 跨度很大**：静场口播类视频 p50 可能只有 1.5，
而全程跟拍的运动视频（抓举）p50 = 13.19，**几乎没有静止段**。
不要用"p50 小"去假设视频很静。阈值仍然自动取 p90。

### 坑一：按"上一帧"比会重复

持续推近的镜头帧间差异一直大，会被切成好几张几乎一样的图。
实测第一次 16 帧里最后 4 张是同一个脸放大。
**改法：与最近一张已保留帧比。**

### 坑二：SSIM 对亮度敏感，去重失效

实测数据（抖音深蹲视频，片尾 logo 光效扫过）：

| 帧对 | SSIM | 归一化相关 | 实际是 |
|------|------|-----------|--------|
| 20.25s vs 22.00s | 0.851 | 0.859 | 同一 logo |
| 20.25s vs 21.50s | 0.588 | 0.646 | 同一 logo |
| 21.50s vs 22.00s | 0.660 | 0.685 | 同一 logo |

SSIM 全部低于 0.9 → 去重失效，连留 3 张 logo。
**改法：先减均值除标准差再算相关系数（`norm_corr`）。**

### 坑三：全局相似度会吃掉一整段动作（2026-11-10 新增）

原 `too_similar` 与**全部**已保留帧比（阈值 0.90）。抓举视频上，
0.0 秒"蹲在杠前"与 6.5 秒"起拉"在 64px 灰度上高度相关，
导致 6.0–8.5 秒的整个动作过程被判为重复、全部丢弃。

根因是**假设错了**：全局比对默认"全片相似 = 重复"，
但这对**同一主体反复做同一姿态**的视频（举重/健身/舞蹈/教学演示）不成立。

**改法：两道去重。**
- 全局：阈值 0.97，只拦"几乎一模一样"的
- 邻近：最近 3 张、2 秒窗口内，阈值 0.90

改完后又发现片尾 logo 从 1 张变 4 张（logo 帧间隔常超过 2 秒窗口，
比对范围空了就全放行）—— 说明两者擅长的事不同，**谁也替代不了谁**。

### 已知局限一：logo 帧用相关性判不出来

实测 dy3（23 秒背蹲）的 `norm_corr` 矩阵，这个结果很反直觉：

| 对比 | 相关度 |
|------|--------|
| logo 帧两两之间 | **0.57 – 0.81** |
| 真实动作帧两两之间 | **0.84 – 0.93** |

**动作帧反而比 logo 帧更像彼此。** 任何能删掉 logo 的相似度阈值，
都会先误杀真实动作帧。

**改法：换正交信号 —— 亮度。** 判据是"相对全片亮度中位数的比值"：

| 视频 | 正片 lum/med | 片尾 logo 段 lum/med |
|------|-------------|---------------------|
| dy3  | 0.98 – 1.02 | 0.00 – 0.36 |
| 抓举 | 0.97 – 1.63 | 0.37 |

分界 0.45（正片最低 0.48，logo 最高 0.36，中间留余量）。
用相对值而非绝对阈值，换个曝光不用重调。

标记写进 `frames.json` 的 `outro: true`，`make_sheet.py` 自动跳过。
**只标记不硬删** —— 万一整条视频是暗调（夜间、直播截图），硬删会掏空内容。

### 已知局限二：片头/片尾数据卡重复，机器认不出

实测 dy3：0.0 秒与 18.25 秒是同一张「165kg×3 REPs」数据卡，
但 `norm_corr` 只有 **0.126**。

原因：0.0 秒那张叠了大字标题「高情背蹲」，18.25 秒那张没有。
64px 灰度看到的是"有字 vs 无字"的结构差异，人看到的是"同一张卡"。

同样是分辨率极限，**看联系表时自己认一下，跳过一个即可**。

**两条局限的共同结论：不要继续调算法。**
64px 特征能可靠区分的是"换了场景/换了主体"，
不是"同一张卡的两种排版"。继续调只会误伤真帧。

### 帧数自适应

按时长取，**这是上限不是目标**（画面真没变化时不会硬凑）：

| 时长 | 帧数上限 |
|------|----------|
| ≤15s | 8 |
| ≤30s | 10 |
| ≤60s | 14 |
| >60s | 18 |

15 秒档从 6 提到 8 是因为 6 帧在 13.7 秒上等于 2.3 秒一帧，太稀。
但**别为了追一个想象中的动作盲目加** —— 曾误判抓举视频"动作被漏掉"，
实际用 20fps 逐帧复核后发现画面上根本没有那个动作。详见下方实测记录。

### 扫描帧率：为什么默认 8 而不是 4

短视频里有效动作常在 1 秒内完成。4fps 的 0.25 秒步长 + `min_gap` 过滤，
很容易把动作过程压成 1 帧。8fps 覆盖更好，而扫描阶段只是低分辨率解码，
13 秒视频也就一两秒的事。

## 实测记录存档

| 日期 | 对象 | 结果 |
|------|------|------|
| 2026-11-10 | `-Xzw-Dp9Xtc` → ID 7700635904671674851 | 图文 6 图，全部下载成功 |
| 2026-11-10 | 作者作品列表（sec_uid `...oyJucPXM3Sh...`） | 21 条，19 视频 / 2 图文 |
| 2026-11-10 | ID 7703952581567452008（165kg 深蹲） | 视频 2.76MB，23.03s，抽 10 帧（5 真帧 + 5 outro） |
| 2026-11-10 | ID 7701898803649395816（188kg 抓举，分享文案带 emoji） | 视频 2.00MB，13.7s，抽 8 帧（7 真帧 + 1 outro） |
| 2026-11-10 | 抓举视频 6.30–7.05s 以 20fps 逐帧复核 | **画面里没有"杠铃过头"，全程远景主体很小**；证实此前"动作被漏帧"的判断是误读 |

### 一次误判的记录（值得看）

2026-11-10 看抓举视频时，我发现抽出的 6 帧里没有"举起"的画面，
判断是抽帧算法漏了快速动作，并据此改了帧预算和去重逻辑。

后来用 20fps 把 6.30–7.05 秒逐帧抽了 16 张才看清：
**那段画面是远景，选手只占画面很小一块，杠铃始终在腰以下，
根本没有"举过头顶"的瞬间。**

教训：**"我没看到"和"画面里没有"是两件事，判断前先补测那个时间窗。**
直接根据"帧里没有"去改算法，会改错方向（我确实改错了两处默认值，
后来不得不改回来）。

