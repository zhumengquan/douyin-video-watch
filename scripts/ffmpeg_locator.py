"""共享的 ffmpeg 定位。三条脚本都从这儿拿，不要各写一份。

为什么单独抽出来：原来 douyin_fetch.py 和 sample_frames.py 各有一份 find_ffmpeg，
两份都硬编码了「上一台机器的工程目录」。换机器后两处一起失效，而且各自报错不一样。
现在统一到一处，换机器只需要在这里改判断逻辑，或者干脆什么都不改（走 PATH）。

查找顺序：
  1. 环境变量 FFMPEG_BIN        —— 用户显式指定，最优先
  2. PATH 里的 ffmpeg            —— 装了系统 ffmpeg / scoop / choco 都走这条
  3. imageio-ffmpeg 自带的二进制  —— pip 装过就白拿一份，不需要系统安装
  4. 常见安装位置（Windows）      —— 最后兜底，只找通用路径，不写死用户名

找不到就返回 None，由调用方给出能照着做的安装提示。
"""
import os
import shutil
import sys


def _from_imageio():
    """imageio-ffmpeg 会随 pip 附一个静态编译的 ffmpeg。"""
    try:
        import imageio_ffmpeg  # noqa: WPS433
    except Exception:
        return None
    try:
        p = imageio_ffmpeg.get_ffmpeg_exe()
        return p if p and os.path.exists(p) else None
    except Exception:
        return None


def _common_windows_paths():
    """只列通用位置，不含任何用户名。"""
    out = []
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            out.append(os.path.join(base, "ffmpeg", "bin", "ffmpeg.exe"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"))
    return out


def find_ffmpeg():
    """返回 ffmpeg 可执行文件路径，找不到返回 None。"""
    env = os.environ.get("FFMPEG_BIN")
    if env and os.path.exists(env):
        return env

    exe = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if exe:
        return exe

    p = _from_imageio()
    if p:
        return p

    if sys.platform == "win32":
        for cand in _common_windows_paths():
            if os.path.exists(cand):
                return cand
    return None


def require_ffmpeg():
    """要不到就直接退出，并给出可照抄的安装命令。"""
    p = find_ffmpeg()
    if p:
        return p
    sys.exit(
        "找不到 ffmpeg。三个办法任选一个：\n"
        "  1) 装一份到系统里，确保 `ffmpeg -version` 能跑（Windows 可用 winget install ffmpeg）\n"
        "  2) pip install imageio-ffmpeg  —— 会顺带下载一个静态编译版，本脚本能直接用\n"
        "  3) 设环境变量 FFMPEG_BIN 指向你的 ffmpeg 可执行文件"
    )
