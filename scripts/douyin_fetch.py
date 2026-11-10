"""抖音内容抓取 —— 基于 2026-11-10 实测的真实接口结构。

## 实测结论（务必读，别再踩一遍）

1. `v.douyin.com/<code>/` **不带重定向**请求 → 302 的 Location 里有视频 ID。
   失效链接会直接跳 `https://www.douyin.com/`，必须显式识别为失效。

2. **SSR/`--dump-dom` 拿不到视频地址。**
   实测：`RENDER_DATA` 207KB 全是 tccConfig / abTest 配置项，零视频地址；
   DOM 里的 `play_addr` 全是配乐 mp3（音乐和视频共用这个字段名，极易误判）；
   `douyinvod` 只出现在 DNS prefetch 里。

3. **正确姿势：playwright 打开视频页，拦 `/aweme/v1/web/aweme/detail/` 的响应。**
   这个接口由页面自己发出、自动签名，返回 200 + 约 40KB JSON。
   Python 直接请求会 403（要 a_bogus），所以必须借页面之手。

   ⚠️ 监听必须挂在 **page** 上，且要在 `new_page()` 之后、`goto()` 之前挂。
   实测挂在 context 层收不到 `request` 事件（会一直是 0）。

4. **内容类型必须先判断，否则白忙。**
   - `aweme_type == 68` / `media_type == 2` / 有 `images` 且 `duration == 0`
     → **图文作品**，没有视频流，没有字幕，应该去下 `images[].url_list`
   - 否则 → 视频作品，去 `video.bit_rate[].play_addr.url_list` 或 `video.play_addr.url_list`

5. **字幕基本没有。** 实测 `is_subtitled: 0`、`video_text: []`、`caption: ""`。
   抖音的字幕是烧在画面里的，不是独立字幕轨。不要指望能拿到字幕文本。

用法:
    python douyin_fetch.py "<分享链接或文案>" <out_dir> [--no-download]
"""
import argparse
import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

SHORT_RE = re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?")
DESK_RE = re.compile(r"https?://(?:www\.)?douyin\.com/(?:video|note)/(\d{15,25})")
ID_IN_URL = re.compile(r"/(?:share/)?(?:video|note)/(\d{15,25})")


def extract_input(text):
    m = SHORT_RE.search(text)
    if m:
        return "short", m.group(0)
    m = DESK_RE.search(text)
    if m:
        return "id", m.group(1)
    t = text.strip()
    if t.isdigit():
        return "id", t
    m = ID_IN_URL.search(t)
    if m:
        return "id", m.group(1)
    return "short", t


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.location = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.location = newurl
        return None


def resolve_id(kind, val):
    if kind == "id":
        return val, None
    h = _NoRedirect()
    op = urllib.request.build_opener(h)
    try:
        op.open(urllib.request.Request(val, headers={"User-Agent": UA}), timeout=20)
    except urllib.error.HTTPError:
        pass
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

    loc = h.location or ""
    bare = loc.rstrip("/")
    if bare in ("https://www.douyin.com", "http://www.douyin.com"):
        return None, "短链已失效（302 直接跳主页）"
    m = ID_IN_URL.search(loc)
    if m:
        return m.group(1), None
    m = re.search(r"(\d{15,25})", loc)
    if m:
        return m.group(1), None
    return None, f"302 里找不到 ID，Location={loc[:180]}"


async def grab_detail(video_id, timeout_s=20):
    """打开视频页并拦截 aweme/detail 响应。返回 (body, 诊断)。"""
    from playwright.async_api import async_playwright

    url = f"https://www.douyin.com/video/{video_id}"
    caught = []

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--autoplay-policy=no-user-gesture-required",
        ])
        ctx = await b.new_context(user_agent=UA,
                                  viewport={"width": 1440, "height": 900},
                                  locale="zh-CN")
        page = await ctx.new_page()

        n_req = [0]

        def on_req(req):
            if "/aweme/" in req.url:
                n_req[0] += 1

        async def on_resp(resp):
            if "/aweme/detail/" not in resp.url:
                return
            try:
                caught.append(await resp.json())
            except Exception:
                pass

        page.on("request", on_req)
        page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        status = None
        try:
            r = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            status = r.status if r else None
        except Exception as e:
            await b.close()
            return None, {"error": f"{type(e).__name__}: {e}", "url": url}

        waited = 0
        while waited < timeout_s * 1000 and not caught:
            await page.wait_for_timeout(1000)
            waited += 1000
        await b.close()

    diag = {"url": url, "status": status, "aweme_requests": n_req[0],
            "detail_responses": len(caught), "waited_ms": waited}
    return (caught[0] if caught else None), diag


def parse_aweme(body):
    """解析 aweme_detail，返回统一结构。区分视频/图文。"""
    aw = (body or {}).get("aweme_detail") or {}
    if not aw:
        return {"kind": "unknown", "reason": "响应里没有 aweme_detail"}

    video = aw.get("video") or {}
    images = aw.get("images") or []
    aweme_type = aw.get("aweme_type")
    media_type = aw.get("media_type")

    author = aw.get("author") or {}
    base = {
        "aweme_id": aw.get("aweme_id"),
        "desc": aw.get("desc") or "",
        "author": author.get("nickname"),
        # sec_uid 是「批量拉这个博主的全部作品」的唯一入口。
        # 拿到它之后用 www.douyin.com/user/<sec_uid> 就能翻作品列表，
        # 不需要登录，也不需要用户一条条粘链接。所以必须存下来。
        "author_sec_uid": author.get("sec_uid"),
        "author_uid": author.get("uid"),
        "author_follower_count": author.get("follower_count"),
        "aweme_type": aweme_type,
        "media_type": media_type,
        "is_subtitled": aw.get("is_subtitled"),
        "has_caption": bool((aw.get("caption") or "").strip()),
        "video_text_count": len(aw.get("video_text") or []),
        "create_time": aw.get("create_time"),
        "statistics": {k: (aw.get("statistics") or {}).get(k)
                       for k in ("digg_count", "comment_count",
                                 "share_count", "collect_count")},
    }

    is_image_post = bool(images) and (video.get("duration") or 0) == 0
    if aweme_type == 68 or media_type == 2 or is_image_post:
        urls = []
        for img in images:
            cand = (img.get("url_list") or img.get("download_url_list") or [])
            if cand:
                urls.append(cand[-1] if "download_url_list" in img else cand[0])
        base.update({"kind": "image_post", "image_count": len(images),
                     "image_urls": urls})
        return base

    # 视频：优先 bit_rate 里最高档，其次 play_addr
    stream = None
    pitch = []
    for br in (video.get("bit_rate") or []):
        pa = br.get("play_addr") or {}
        urls = pa.get("url_list") or []
        if urls:
            pitch.append({"url": urls[0], "w": pa.get("width"),
                          "h": pa.get("height"),
                          "bit_rate": br.get("bit_rate"),
                          "gear": br.get("gear_name"),
                          "size": pa.get("data_size")})
    if not pitch:
        pa = video.get("play_addr") or {}
        for u in (pa.get("url_list") or []):
            pitch.append({"url": u, "w": pa.get("width"), "h": pa.get("height")})

    # 挡掉配乐 mp3 冒充视频（实测踩过）
    pitch = [x for x in pitch if not re.search(r"\.mp3(\?|$)", x["url"])]
    pitch.sort(key=lambda x: (x.get("bit_rate") or 0), reverse=True)
    if pitch:
        stream = pitch[0]["url"]

    base.update({"kind": "video", "stream_url": stream,
                 "variants": pitch[:5],
                 "duration_ms": video.get("duration"),
                 "width": video.get("width"), "height": video.get("height"),
                 "cover": ((video.get("cover") or {}).get("url_list") or [None])[0]})
    return base


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


def download(ffmpeg, url, out_path):
    import subprocess
    cmd = [ffmpeg, "-v", "error", "-y",
           "-headers", "Referer: https://www.douyin.com/\r\n",
           "-user_agent", UA,
           "-i", url, "-c", "copy", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    ok = os.path.exists(out_path) and os.path.getsize(out_path) > 10240
    return ok, (r.stderr or "")[-600:]


def download_images(urls, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for i, u in enumerate(urls):
        ext = ".webp" if ".webp" in u else ".jpeg"
        p = os.path.join(out_dir, f"img_{i:03d}{ext}")
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": UA, "Referer": "https://www.douyin.com/"})
            with urllib.request.urlopen(req, timeout=30) as r, open(p, "wb") as f:
                f.write(r.read())
            if os.path.getsize(p) > 2048:
                saved.append(p)
        except Exception:
            pass
    return saved


async def main_async(args):
    os.makedirs(args.out_dir, exist_ok=True)
    kind, val = extract_input(args.share)
    vid, err = resolve_id(kind, val)
    result = {"input": args.share, "video_id": vid, "id_error": err}
    if not vid:
        result["verdict"] = "解析失败"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    body, diag = await grab_detail(vid)
    result["diag"] = diag
    if not body:
        result["verdict"] = "没拦到 aweme/detail 响应"
        result["hint"] = ("检查 diag.aweme_requests。若为 0，页面可能没正常加载；"
                          "若 >0 但 detail_responses=0，可能是响应体读取时机问题。")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    parsed = parse_aweme(body)
    result.update(parsed)
    ff = find_ffmpeg()

    if parsed.get("kind") == "video" and parsed.get("stream_url") and not args.no_download:
        if ff:
            out = os.path.join(args.out_dir, "video.mp4")
            ok, err2 = download(ff, parsed["stream_url"], out)
            result["downloaded"] = ok
            if ok:
                result["video_path"] = out
                result["video_size"] = os.path.getsize(out)
            else:
                result["download_error"] = err2
    elif parsed.get("kind") == "image_post" and not args.no_download:
        result["images_saved"] = download_images(parsed.get("image_urls") or [],
                                                 os.path.join(args.out_dir, "images"))

    with open(os.path.join(args.out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    slim = {k: result.get(k) for k in
            ("video_id", "kind", "desc", "author", "author_sec_uid",
             "image_count", "downloaded", "video_size", "images_saved")}
    print(json.dumps(slim, ensure_ascii=False, indent=2))
    if parsed.get("kind") == "image_post":
        print("注意：这是图文作品，没有视频流。")
    if result.get("author_sec_uid"):
        print(f"想批量看这个博主的全部作品：\n"
              f"  python scripts/douyin_author.py "
              f"\"{result['author_sec_uid']}\" <输出目录>")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("share")
    ap.add_argument("out_dir")
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args()
    r = asyncio.run(main_async(a))
    sys.exit(0 if r.get("video_id") else 1)


if __name__ == "__main__":
    main()
