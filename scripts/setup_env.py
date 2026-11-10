#!/usr/bin/env python
"""环境自检 / 一键安装。换机器后第一件事跑这个。

用法：
    python scripts/setup_env.py --check    # 只体检，不装任何东西
    python scripts/setup_env.py            # 缺什么装什么
    python scripts/setup_env.py --force    # 连浏览器二进制也重装

设计意图：
    这个 skill 换机器部署时，最容易挂的不是代码，是「这个通了那个没通」。
    以前的经验是两份 find_ffmpeg 各写一份、各自硬编码本机路径，
    换机器后同时失效且报错不一样。所以这里把「能不能跑」变成一个可以
    一次问清的问题，而不是四个脚本各报各的错。
"""
import argparse
import importlib
import os
import subprocess
import sys

MIRROR = "https://mirrors.tencent.com/pypi/simple/"
MIRROR_HOST = "mirrors.tencent.com"
PW_MIRROR = "https://npmmirror.com/mirrors/playwright"

# 包名 -> import 名（两者不一定一致）
# 只列真正必需的。imageio-ffmpeg 是 ffmpeg 找不到时的备选，不算必需，单独处理。
PACKAGES = {
    "playwright": "playwright",
    "numpy": "numpy",
    "Pillow": "PIL",
    "requests": "requests",
    "pyyaml": "yaml",
}
OPTIONAL = {
    "imageio-ffmpeg": "imageio_ffmpeg",
}


def has_module(mod):
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def run(cmd, env=None, timeout=600):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       errors="replace", env=e, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def check():
    """返回 (结果字典, 是否全部就绪)。"""
    res = {"python": sys.version.split()[0], "missing": []}
    for pkg, mod in PACKAGES.items():
        if has_module(mod):
            res[pkg] = "ok"
        else:
            res[pkg] = "MISSING"
            res["missing"].append(pkg)

    # ffmpeg
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from ffmpeg_locator import find_ffmpeg
        ff = find_ffmpeg()
    except Exception as e:
        ff = None
        res["ffmpeg_error"] = str(e)
    res["ffmpeg"] = ff or "MISSING"
    if not ff:
        res["missing"].append("ffmpeg")

    # 可选包的展示（不计入 missing）
    for pkg, mod in OPTIONAL.items():
        res[pkg] = "ok" if has_module(mod) else "未装（可选）"

    # chromium
    if res.get("playwright") == "ok":
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            try:
                exe = pw.chromium.executable_path
                ok = os.path.exists(exe)
                res["chromium"] = exe if ok else "MISSING"
            finally:
                pw.stop()
            if not ok:
                res["missing"].append("chromium")
        except Exception as e:
            res["chromium"] = f"ERROR: {e}"
            res["missing"].append("chromium")
    else:
        res["chromium"] = "skipped (playwright 未装)"
        res["missing"].append("chromium")

    return res, not res["missing"]


def install(force=False):
    """按镜像装缺失的包；再补浏览器二进制。"""
    missing = [p for p, m in PACKAGES.items() if not has_module(m)]
    if missing:
        print(f"→ 装 python 包：{', '.join(missing)}", flush=True)
        cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir",
               "-i", MIRROR, "--trusted-host", MIRROR_HOST] + missing
        rc, out = run(cmd, timeout=900)
        print("  " + ("OK" if rc == 0 else "FAILED"))
        if rc != 0:
            print("  " + out[-1200:])
    else:
        print("→ python 包齐了", flush=True)

    # ffmpeg 仍缺，就用 imageio-ffmpeg 兜底
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ffmpeg_locator import find_ffmpeg
    if not find_ffmpeg():
        print("→ ffmpeg 找不到，装 imageio-ffmpeg 兜底（不需要系统安装）", flush=True)
        rc, out = run([sys.executable, "-m", "pip", "install", "--no-cache-dir",
                       "-i", MIRROR, "--trusted-host", MIRROR_HOST,
                       "imageio-ffmpeg"], timeout=600)
        print("  " + ("OK" if rc == 0 else "FAILED"))
        if rc != 0:
            print("  " + out[-800:])

    # chromium：只有真的拿到可执行文件路径才算装好
    if force or "chromium" in check()[0].get("missing", []):
        print("→ 装 playwright chromium（走 npmmirror）", flush=True)
        rc, out = run([sys.executable, "-m", "playwright", "install", "chromium"],
                      env={"PLAYWRIGHT_DOWNLOAD_HOST": PW_MIRROR}, timeout=1200)
        print("  " + ("OK" if rc == 0 else "FAILED"))
        if rc != 0:
            print("  " + out[-1200:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只体检，不安装")
    ap.add_argument("--force", action="store_true", help="连 chromium 也重装")
    args = ap.parse_args()

    if not args.check:
        install(force=args.force)

    res, ready = check()
    print("\n=== 环境体检 ===")
    for k, v in res.items():
        if k == "missing":
            continue
        print(f"  {k:14s} {v}")
    print()
    if ready:
        print("🟢 全部就绪，可以直接开始看视频。")
        return 0
    print(f"🔴 还缺：{', '.join(res['missing'])}")
    print("   再跑一次 `python scripts/setup_env.py` 尝试自动补齐。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
