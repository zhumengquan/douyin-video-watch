#!/usr/bin/env python
"""批量拉一个抖音博主的全部公开作品，可选直接下载。

为什么需要这个：分享链接一条一条粘太低效。拿到博主的 sec_uid 之后，
就能列出他所有作品（标题、时长、类型、ID），再挑着看。

**不需要登录** —— 实测作者主页的作品列表接口游客态就能访问。
（对比：搜索接口明确要求登录，页面上写着"登录后即可搜索更多精彩视频"。）

sec_uid 从哪来：
  跑一次 douyin_fetch.py，它现在会把 author_sec_uid 写进 meta.json。
  或者从任意视频详情页的 author.sec_uid 拿。

用法:
    python douyin_author.py <sec_uid 或主页URL> <输出目录> [--max 50] [--download]

    --download   把列出来的作品全部下载（视频下 mp4、图文下 jpg）
"""
import argparse
import asyncio
import json
import os
import re
import sys

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def extract_sec_uid(s):
    """接受 sec_uid、完整主页 URL、或带 sec_uid 的任意文本。"""
    s = s.strip()
    m = re.search(r"/user/([A-Za-z0-9_\-]+)", s)
    if m:
        return m.group(1)
    if s.startswith("MS4wLjAB"):
        return s
    return s


async def grab_posts(sec_uid, max_posts, timeout_s=40):
    """打开主页，拦 /aweme/v1/web/aweme/post/ 拿作品列表。"""
    from playwright.async_api import async_playwright

    url = f"https://www.douyin.com/user/{sec_uid}"
    caught = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = await browser.new_context(user_agent=UA,
                                        viewport={"width": 1440, "height": 900},
                                        locale="zh-CN")
        page = await ctx.new_page()

        async def on_resp(resp):
            if "/aweme/v1/web/aweme/post/" in resp.url:
                try:
                    body = await resp.text()
                    if body:
                        caught.append(body)
                except Exception:
                    pass

        page.on("response", on_resp)          # 必须在 goto 之前挂

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass

        waited = 0
        while waited < timeout_s * 1000 and not caught:
            await page.wait_for_timeout(1000)
            waited += 1000

        # 滚动几次加载更多
        if caught:
            for _ in range(3):
                await page.mouse.wheel(0, 3000)
                await page.wait_for_timeout(1500)

        await browser.close()

    posts, seen = [], set()
    for body in caught:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        for aw in (data.get("aweme_list") or []):
            aid = aw.get("aweme_id")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            video = aw.get("video") or {}
            images = aw.get("images") or []
            posts.append({
                "aweme_id": aid,
                "type": "image" if (aw.get("aweme_type") == 68
                                   or aw.get("media_type") == 2
                                   or (images and not (video.get("duration") or 0)))
                        else "video",
                "duration_ms": video.get("duration") or 0,
                "desc": (aw.get("desc") or "").replace("\n", " "),
                "create_time": aw.get("create_time"),
                "statistics": {k: (aw.get("statistics") or {}).get(k)
                               for k in ("digg_count", "comment_count")},
                "url": f"https://www.douyin.com/video/{aid}",
            })
    return posts[:max_posts] if max_posts else posts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sec_uid", help="sec_uid 或主页 URL")
    ap.add_argument("out_dir")
    ap.add_argument("--max", type=int, default=50, help="最多列几条，0=不限")
    ap.add_argument("--download", action="store_true", help="顺便下载全部作品")
    args = ap.parse_args()

    sec_uid = extract_sec_uid(args.sec_uid)
    os.makedirs(args.out_dir, exist_ok=True)

    posts = asyncio.run(grab_posts(sec_uid, args.max))
    if not posts:
        sys.exit("没拦到作品列表。可能是 sec_uid 不对，或页面没加载出来。")

    meta = {"sec_uid": sec_uid, "count": len(posts), "posts": posts}
    path = os.path.join(args.out_dir, "posts.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    n_v = sum(1 for p in posts if p["type"] == "video")
    print(json.dumps({"sec_uid": sec_uid, "total": len(posts),
                      "videos": n_v, "images": len(posts) - n_v,
                      "saved": path}, ensure_ascii=False, indent=2))
    for p in posts:
        sec = (p["duration_ms"] or 0) / 1000
        print(f"  [{p['type']:5s}] {p['aweme_id']}  {sec:5.1f}s  "
              f"{p['desc'][:52]}")

    if not args.download:
        print("\n加 --download 可把上面这些全部下载下来。")
        return

    fetch = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "douyin_fetch.py")
    ok = 0
    for i, p in enumerate(posts, 1):
        d = os.path.join(args.out_dir, p["aweme_id"])
        print(f"\n[{i}/{len(posts)}] {p['aweme_id']} {p['desc'][:40]}")
        r = asyncio.run(_run_fetch(fetch, p["url"], d))
        if r:
            ok += 1
    print(f"\n下载完成 {ok}/{len(posts)}")


async def _run_fetch(fetch, url, out):
    import subprocess
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-u", fetch, url, out,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out_b, _ = await proc.communicate()
    txt = out_b.decode("utf-8", "replace") if out_b else ""
    print("   " + " | ".join(txt.strip().splitlines()[:2])[:150])
    return proc.returncode == 0


if __name__ == "__main__":
    main()
