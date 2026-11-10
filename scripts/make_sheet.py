#!/usr/bin/env python
"""把关键帧拼成一张联系表，供 agent 一次看完。

为什么要这个脚本：agent 一次读一张图很浪费上下文，而且分不清顺序。
拼成一张带时间戳标注的大图，一次 Read 就能看到全片脉络。

会自动跳过 frames.json 里标了 outro 的帧（片尾 logo / 黑场），
这类帧没有信息量，占位置还会误导判断。

用法:
    python make_sheet.py <frames目录或 frames.json> <输出.jpg> [--cols 4] [--skip-outro]

    <frames目录>  传 sample_frames.py 的输出目录（含 frames.json）即可，
                  脚本会自己去读同级的 frames.json
"""
import argparse
import glob
import json
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("需要 Pillow：pip install Pillow")


def load_meta(path):
    """传入目录或 frames.json，返回 (frames 列表, outro 时间戳集合)。"""
    if os.path.isdir(path):
        j = os.path.join(path, "frames.json")
    else:
        j = path
    if not os.path.exists(j):
        return None, set()
    with open(j, encoding="utf-8") as f:
        meta = json.load(f)
    outro = {round(fr["t"], 2) for fr in meta.get("frames", []) if fr.get("outro")}
    return meta.get("frames", []), outro


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="frames 目录，或 frames.json 路径")
    ap.add_argument("out", help="输出 jpg 路径")
    ap.add_argument("--cols", type=int, default=4, help="每行几张")
    ap.add_argument("--cell-w", type=int, default=300, help="单格宽度")
    ap.add_argument("--cell-h", type=int, default=533, help="单格高度")
    ap.add_argument("--keep-outro", action="store_true",
                    help="保留片尾 logo/黑场帧（默认跳过）")
    args = ap.parse_args()

    meta, outro = load_meta(args.src)
    if meta is not None:
        # 用 frames.json 的顺序和时间戳，最准确
        items = []
        for fr in meta:
            p = fr["path"]
            if not os.path.isabs(p):
                base = args.src if os.path.isdir(args.src) else os.path.dirname(args.src)
                p = os.path.join(base, os.path.basename(p)) if not os.path.exists(p) else p
            if not os.path.exists(p):
                continue
            if fr.get("outro") and not args.keep_outro:
                continue
            items.append((fr["t"], p))
    else:
        # 没有 frames.json 就退回按文件名排序，时间从文件名里抠
        d = args.src
        items = []
        for p in sorted(glob.glob(os.path.join(d, "*.jpg"))):
            base = os.path.basename(p)
            try:
                hhmmss = base.split("_")[1].replace(".jpg", "")
                h, m, s = int(hhmmss[:2]), int(hhmmss[2:4]), float(hhmmss[4:])
                t = h * 3600 + m * 60 + s
            except (IndexError, ValueError):
                t = 0.0
            items.append((t, p))

    if not items:
        sys.exit("没有可用的帧")

    cols = args.cols
    tw, th = args.cell_w, args.cell_h
    pad, label_h = 6, 26
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + label_h)), (240, 240, 240))
    draw = ImageDraw.Draw(sheet)

    for i, (t, p) in enumerate(items):
        im = Image.open(p).convert("RGB")
        im.thumbnail((tw - pad, th - pad))
        x = (i % cols) * tw
        y = (i // cols) * (th + label_h)
        sheet.paste(im, (x + (tw - im.width) // 2, y + label_h))
        mm, ss = int(t // 60), t % 60
        draw.text((x + 6, y + 6), f"#{i}  {mm:02d}:{ss:05.2f}", fill=(10, 10, 10))

    sheet.save(args.out, quality=90)
    skipped = len(meta) - len(items) if meta else 0
    print(json.dumps({"frames": len(items), "skipped_outro": skipped,
                      "size": sheet.size}, ensure_ascii=False))
    print(f"联系表: {args.out}")


if __name__ == "__main__":
    main()
