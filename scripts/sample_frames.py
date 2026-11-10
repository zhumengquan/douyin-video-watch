#!/usr/bin/env python
"""信息量驱动的抽帧。

抖音这类短视频的问题是：均匀抽帧会抽出一堆几乎相同的画面。
一个 60 秒口播视频，每 3 秒抽一张，20 张里可能有 15 张是同一张脸。

这个脚本反过来做：先用低分辨率快速扫一遍全片，算出每一帧相对上一帧的
视觉差异，只在画面真的变化时保留关键帧。人脸特写、静止口播、纯色底
都会自动合并。

用法:
    python sample_frames.py <video> <out_dir> [--max 20] [--min-gap 0.5]
                            [--scene 0.12] [--scan-fps 4]

输出:
    <out_dir>/frames/*.jpg
    <out_dir>/frames.json   每帧的时间戳与差异分数，供 agent 对齐字幕
"""
import argparse
import json
import math
import os
import subprocess
import sys

try:
    import numpy as np
    from PIL import Image
except ImportError:
    sys.exit("需要 numpy 和 Pillow")


def find_ffmpeg():
    """找 ffmpeg。逻辑统一在 ffmpeg_locator 里，这里只做转发。

    原来这里硬编码了本机某个工程目录，换机器就失效。
    """
    try:
        from ffmpeg_locator import find_ffmpeg as _f
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from ffmpeg_locator import find_ffmpeg as _f
    return _f()


def probe_duration(ffmpeg, video):
    """用 ffmpeg 自带信息拿时长，避免依赖 ffprobe。"""
    out = subprocess.run(
        [ffmpeg, "-i", video], capture_output=True, text=True, errors="ignore"
    ).stderr
    for line in out.splitlines():
        if "Duration:" in line:
            part = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = part.split(":")
            return float(h) * 3600 + float(m) * 60 + float(s)
    return None


def scan_frames(ffmpeg, video, scan_fps, width=64):
    """低分辨率扫描全片，返回 (时间戳数组, 特征数组)。

    缩到 64px 宽是刻意的：这个尺寸下画面细节消失，留下的只有构图、
    明暗、主体位置的粗变化——正好是我们判断"画风变了没"需要的信号。
    """
    height = max(2, int(width * 16 / 9) // 2 * 2)
    cmd = [
        ffmpeg, "-v", "error", "-i", video,
        "-vf", f"fps={scan_fps},scale={width}:{height}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True).stdout
    frame_size = width * height * 3
    n = len(raw) // frame_size
    if n == 0:
        return np.array([]), np.zeros((0, frame_size))

    arr = np.frombuffer(raw[: n * frame_size], dtype=np.uint8)
    arr = arr.reshape(n, frame_size).astype(np.float32)
    times = np.arange(n) / scan_fps
    return times, arr


def ssim_simple(a, b):
    """(保留备用) 简化版 SSIM。

    实测结论：SSIM 不适合本场景。它把"整体亮度/对比度变化"也算成不相似，
    而视频里光效扫过、镜头自动曝光都会改亮度——
    实测片尾 logo 光效扫过时视觉上同一帧，SSIM 只有 0.85，去重失效。
    现在主判据改成 norm_corr()。
    """
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu1, mu2 = float(a.mean()), float(b.mean())
    v1, v2 = float(a.var()), float(b.var())
    cov = float(((a - mu1) * (b - mu2)).mean())
    return (((2 * mu1 * mu2 + c1) * (2 * cov + c2)) /
            ((mu1 ** 2 + mu2 ** 2 + c1) * (v1 + v2 + c2)))


def norm_corr(a, b):
    """亮度/对比度归一化后的相关系数。本脚本的去重主判据。

    做法：每帧先减均值除标准差（等于把曝光差异抹掉），再算相关系数。
    对"同一画面但在变亮/变暗"很稳，对"真的换了内容"依然敏感。

    实测依据：
      - 掩耳盗铃片尾连拍脸：相关系数 > 0.90（正确识别为重复）
      - 抖音片尾 logo 光效扫过：SSIM 0.85 / 相关系数 > 0.95（SSIM 漏了，它抓到了）
      - 真的换了镜头：相关系数 < 0.5
    """
    aa = a.astype(np.float32)
    bb = b.astype(np.float32)
    aa = aa - aa.mean()
    bb = bb - bb.mean()
    na = float(np.sqrt((aa * aa).sum()))
    nb = float(np.sqrt((bb * bb).sum()))
    if na < 1e-6 or nb < 1e-6:
        # 纯色帧（黑场/白场）：彼此几乎相同，和别的差异极大
        return 1.0 if abs(float(a.std()) - float(b.std())) < 3.0 else 0.0
    return float((aa * bb).sum() / (na * nb))


def pick_keyframes(times, feats, max_frames, min_gap, scene_thresh,
                   ssim_max=0.90, feat_shape=None, lookback=3, window_s=2.0,
                   dup_max=0.97):
    """按差异分数挑关键帧。

    核心不是"和上一帧比"，而是"和上一张已保留的帧比"。
    原因（实测踩到）：一个持续运动的镜头（推镜、脸放大、循环动画）
    帧间差异一直很大，按帧比会把它切成好几张几乎相同的图。
    按已保留帧比，持续运动只会在偏离够远时才再留一张。

    两道判据（缺一不可，实测数据支撑）：
      - 差异值    ：与上一张保留帧的平均绝对差，判断"变化够不够大"
      - norm_corr ：与**邻近**已保留帧的归一化相关，判断"是不是同一件事"
    只过第一道会留下大量"同一动作的不同瞬间"，看着不一样、信息是重复的。

    为什么用 norm_corr 而不是 SSIM（实测踩到）：
      片尾 logo 有光效扫过，视觉上是同一帧，SSIM 只有 0.85（它把亮度变化算成不相似），
      去重失效、连留 3 张。归一化相关系数对曝光变化不敏感，这类能正确拦住。

    阈值来源：实测两段视频的帧间差异分布（64px 灰度特征、4fps 扫描）
      p50≈1.5-13  p80≈4-26  p90≈19-34  p95≈34-46  max≈70
    注意 p50 的跨度很大：静场口播视频 p50 只有 1.5，而全程跟拍的运动视频
    （抓举实测 p50=13.19）几乎没有静止段。所以不要用"p50 小"去假设视频很静。

    规则：
      1. 第一帧永远保留
      2. 与最近一张保留帧的差异超过阈值，且与邻近已保留帧都不太像时保留
      3. 还要过一道 min_gap 时间间隔
      4. 候选太多就按分数取高分；画面太静就均匀补齐
    """
    if len(feats) == 0:
        return []

    n_feat = len(feats[0])
    # 扫描用的特征是按 scan 分辨率展平的 RGB，这里还原成灰度图做相似度。
    # 长宽不一定相等（64 宽、高按 16:9 取整），所以必须分别推。
    gray = None
    if n_feat % 3 == 0:
        px = n_feat // 3
        # 找一对整数边长，优先宽度 64~96 之间
        for w in range(96, 15, -1):
            if px % w == 0:
                h = px // w
                if 8 <= h <= 400:
                    rgb = feats.reshape(len(feats), h, w, 3)
                    gray = rgb.mean(axis=3).reshape(len(feats), h, w)
                    break

    # 先算一遍帧间差异，用来定自适应阈值
    if len(feats) > 1:
        step = np.abs(np.diff(feats, axis=0)).mean(axis=1)
    else:
        step = np.array([0.0])

    if scene_thresh is None:
        auto = float(np.percentile(step, 90))
        scene_thresh = max(auto, 2.0)
    thresh = float(scene_thresh)

    picked = [0]
    last_t = times[0]

    def too_similar(i):
        """两道去重：全局拦"几乎一模一样"，邻近拦"中等相似"。

        这里改过两次，两次都是实测翻车逼出来的，记录清楚：

        【第一次】原来只有全局比对（跟全部已保留帧比，阈值 0.90）。
        抓举视频上它把整段动作吃掉了：0.0 秒"人蹲在杠前"和 6.5 秒"起拉"
        在 64px 灰度上相关度很高（同一个主体、同一构图、相似的低姿态），
        于是动作过程被判成"已经拍过了"全部丢弃。
        教训：全局比对的隐含假设是"全片相似 = 重复"，但这对
        **同一主体反复做同一姿态**的视频（举重/健身/舞蹈/教学演示）不成立。

        【第二次】改成只看邻近帧（最近 lookback 张、window_s 秒内），
        结果片尾 logo 从 1 张变成 4 张：logo 帧之间间隔常常超过 2 秒窗口，
        比对范围空了，全部放行。
        教训：全局比对恰恰擅长拦这种"首尾呼应、中间隔很远"的重复点缀帧。

        所以两个都要，分工不同：
          - 全局：阈值放到 dup_max（0.97），只拦"几乎逐像素雷同"的
          - 邻近：阈值用 ssim_max（0.90），拦同一段落内的近似帧

        ⚠️ 但要清楚这两道都拦不住片尾 logo 的连拍。实测 dy3（23 秒背蹲）：
          logo 帧两两之间 norm_corr 只有 0.57-0.81，
          而真实动作帧之间高达 0.84-0.93 ——
          也就是说在这个特征空间里，**动作帧反而比 logo 帧更像彼此**。
          任何能拦住 logo 的阈值都会先误杀真实动作帧。
          结论：logo 帧靠算法删不掉，靠看图的人跳过。别再往这个方向调了。
        """
        if gray is None:
            return False
        # 全局硬去重：只对"几乎一模一样"的生效
        if any(norm_corr(gray[i], gray[j]) > dup_max for j in picked):
            return True
        # 邻近软去重：这一段里已经拍过类似画面了
        recent = [j for j in picked
                  if window_s is None or times[i] - times[j] <= window_s]
        if lookback:
            recent = recent[-lookback:]
        return any(norm_corr(gray[i], gray[j]) > ssim_max for j in recent)

    for i in range(1, len(feats)):
        if times[i] - last_t < min_gap:
            continue
        ref = picked[-1]
        diff = float(np.abs(feats[i] - feats[ref]).mean())
        if diff < thresh:
            continue
        if too_similar(i):
            continue
        picked.append(i)
        last_t = times[i]

    # 裁剪取舍用的分数：用【相邻扫描帧】的绝对差异，而不是"相对上一张保留帧"。
    #
    # 这里踩过一个坑：原来用"相对上一张保留帧"，结果帧越密集分数越低 ——
    # 因为密集区的相邻保留帧差别本来就小。于是按分数裁剪时，
    # 一整段快速动作（抓举 6.0-8.5 秒）恰好因为密集而被整体裁掉，
    # 留下的是稀疏区里那些"差异大"的孤立帧。方向完全反了。
    #
    # 现在用 step[i]：第 i 帧相对第 i-1 帧的变化。这个值只取决于画面本身，
    # 与抽帧密度无关，越剧烈的地方分越高，正是裁剪时该保住的。
    scores = {}
    for k, i in enumerate(picked):
        scores[i] = 0.0 if i == 0 else float(step[max(i - 1, 0)])
    top = max(scores.values()) if scores else 1.0
    if top <= 0:
        top = 1.0
    norm = {i: v / top for i, v in scores.items()}

    if len(picked) > max_frames:
        # 预算不够时优先保住"变化最剧烈"的帧，而不是时间上均匀的帧。
        #
        # 关于"第一张和最后一张恒定保留"—— 试过，有坑：
        # dy3 里 0.0 秒和 18.25 秒都是同一张"165kg×3 REPs"数据卡
        # （片头片尾呼应），两条都硬保就白占一格。
        # 所以最后一张只是"优先保留"，不是无条件保留：它得先过全局去重。
        keep = {picked[0]}
        last = picked[-1]
        if gray is not None and any(
                norm_corr(gray[last], gray[j]) > dup_max for j in keep):
            last = None
        elif gray is None:
            last = None
        if last is not None:
            keep.add(last)
        rest = sorted((i for i in picked[1:] if i not in keep),
                      key=lambda i: norm[i], reverse=True)
        picked = sorted(keep | set(rest[: max(1, max_frames - len(keep))]))

    if len(picked) < min(max_frames, 6) and len(times) > 1:
        need = min(max_frames, 6)
        even = np.linspace(0, times[-1], need)
        idx = [int(np.argmin(np.abs(times - t))) for t in even]
        picked = sorted(set(picked) | set(idx))
        for i in picked:
            norm.setdefault(i, 0.0)

    return [(float(times[i]), float(norm.get(i, 0.0)), int(i)) for i in picked]


def mark_outro_frames(feats, picked_idx):
    """标出片尾 logo / 黑场帧。只做标记，不删除。

    为什么不用相关性做这件事（试过，失败）：
      实测 dy3 里 logo 帧两两 norm_corr 只有 0.57-0.81，
      而真实动作帧之间高达 0.84-0.93 —— 动作帧反而更"像"彼此。
      任何能删掉 logo 的相似度阈值，都会先误杀真实动作帧。

    换成亮度这个正交信号，按"相对全片亮度中位数的比值"判，而不是绝对阈值：

      | 视频 | 正片 lum/med | 片尾 logo 段 lum/med |
      |------|-------------|---------------------|
      | dy3  | 0.98-1.02   | 0.00-0.36           |
      | e2e  | 0.97-1.63   | 0.37                |

    用相对值的理由：绝对亮度阈值换个曝光就得重调，相对中位数天然归一化。
    分界取 0.45 —— 实测正片最低 0.48，logo 段最高 0.36，中间留了余量。

    返回 {帧序号: True}，由调用方写进 frames.json 的 "outro" 字段。
    不做硬删除的原因：万一某条视频全片就是暗调（夜间、直播截图），
    自动删会把整条视频掏空。标记出来交给看图的人判断更安全。
    """
    if len(feats) == 0 or not picked_idx:
        return {}
    lum = feats.mean(axis=1)
    med = float(np.median(lum))
    if med < 1e-6:
        return {}
    return {i: True for i in picked_idx if lum[i] / med < 0.45}


def extract_at(ffmpeg, video, out_dir, stamps, width=720, outro=None):
    os.makedirs(out_dir, exist_ok=True)
    outro = outro or {}
    results = []
    for k, (t, score, src_i) in enumerate(stamps):
        hh, mm, ss = int(t // 3600), int(t % 3600 // 60), t % 60
        name = f"{k:02d}_{hh:02d}{mm:02d}{ss:05.2f}.jpg"
        path = os.path.join(out_dir, name)
        subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video,
             "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", path],
            capture_output=True,
        )
        if os.path.exists(path) and os.path.getsize(path) > 0:
            item = {"index": k, "t": round(t, 2), "score": round(score, 3),
                    "path": path, "size": os.path.getsize(path)}
            if outro.get(src_i):
                item["outro"] = True
            results.append(item)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out_dir")
    ap.add_argument("--max", type=int, default=0,
                    help="最多保留几帧；0=按视频时长自适应（默认）")
    ap.add_argument("--min-gap", type=float, default=0.25,
                    help="相邻帧最小间隔秒（默认 0.25，约等于扫描步长）")
    ap.add_argument("--scene", type=float, default=None,
                    help="场景切换阈值（绝对差异值，实测 p90≈20-34）。不传则自动取 p90")
    ap.add_argument("--ssim-max", type=float, default=0.90,
                    help="归一化相关上限，超过视为重复帧（实测 0.9 是干净分界）")
    ap.add_argument("--scan-fps", type=float, default=8.0,
                    help="扫描采样率。默认 8。理由是一般短视频里有效动作常在 1 秒内完成，"
                         "4fps 的 0.25 秒步长只能碰到 2-4 个点；8fps 覆盖更好，"
                         "而且扫描阶段只是低分辨率解码，13 秒视频也就一两秒的事")
    ap.add_argument("--width", type=int, default=720, help="输出图宽度")
    args = ap.parse_args()

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        sys.exit("找不到 ffmpeg，请设置 FFMPEG_BIN 环境变量")

    dur = probe_duration(ffmpeg, args.video)
    times, feats = scan_frames(ffmpeg, args.video, args.scan_fps)
    if len(times) == 0:
        sys.exit("解码失败：没读到任何帧")

    # 帧数上限：不传就按视频长度自适应。
    #
    # 定这个数时踩过一次错，记下来免得再犯：
    # 一开始以为 13.7 秒抓举视频"提拉动作被漏掉了"，就把 ≤15 秒的预算
    # 从 6 提到 8。后来用 20fps 逐帧把 6.30-7.05 秒全抽出来看，才发现
    # **那段画面里根本没有"杠铃举过头顶"**——全程远景，人只占画面很小一块，
    # 是极快的发力后放下，不是完整抓举。我看到的"动作消失"是误读，
    # 不是抽帧漏帧。
    #
    # 所以预算按信息密度给，不要为了追一个想象中的动作盲目加：
    # ≤15 秒 8 张已经够用（13.7 秒实测覆盖了准备/拉起/落地/庆祝/离场/片尾）。
    # 真觉得不够，用 --max 手动加，别改默认值。
    if args.max > 0:
        cap = args.max
    elif dur:
        if dur <= 15:
            cap = 8
        elif dur <= 30:
            cap = 10
        elif dur <= 60:
            cap = 14
        else:
            cap = 18
    else:
        cap = 12

    stamps = pick_keyframes(times, feats, cap, args.min_gap, args.scene,
                            args.ssim_max)
    outro = mark_outro_frames(feats, [s[2] for s in stamps])
    frames = extract_at(ffmpeg, args.video, os.path.join(args.out_dir, "frames"),
                        stamps, args.width, outro)

    meta = {
        "video": os.path.abspath(args.video),
        "duration": round(dur, 2) if dur else None,
        "scanned_frames": len(times),
        "scan_fps": args.scan_fps,
        "kept": len(frames),
        "params": {"max": args.max, "min_gap": args.min_gap,
                   "scene": args.scene, "ssim_max": args.ssim_max,
                   "scan_fps": args.scan_fps, "width": args.width},
        "frames": frames,
        "outro_count": sum(1 for f in frames if f.get("outro")),
    }
    with open(os.path.join(args.out_dir, "frames.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(json.dumps({k: meta[k] for k in
                      ("duration", "scanned_frames", "kept", "outro_count")},
                     ensure_ascii=False))
    if meta["outro_count"]:
        ts = [f"{f['t']:.2f}" for f in frames if f.get("outro")]
        print(f"注意：{meta['outro_count']} 帧疑似片尾 logo/黑场（t={','.join(ts)}），"
              f"已在 frames.json 标 outro，看图时可跳过")
    print(f"输出目录: {os.path.join(args.out_dir, 'frames')}")


if __name__ == "__main__":
    main()
