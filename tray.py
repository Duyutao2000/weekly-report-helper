"""
托盘模式启动器（由 start.bat 调用）。

- 以 pythonw 无窗口方式后台常驻，右下角托盘显示图标
- 服务就绪后自动打开默认浏览器（Gradio inbrowser）
- 托盘菜单：双击图标或菜单项可随时打开周报页面；"退出"结束进程
- 重复启动保护：端口已被占用时不再起服务，仅打开页面
- 崩溃日志：data/tray.log（pythonw 无控制台，异常必须落盘）
"""
import os
import socket
import sys
import threading
import traceback
import webbrowser

# 启动提速：禁用遥测上报（省掉 Gradio 启动期的网络请求）
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
os.environ.setdefault("DO_NOT_TRACK", "1")

from PIL import Image, ImageDraw
import pystray

HOST = "127.0.0.1"
PORT = 7860
URL = f"http://{HOST}:{PORT}"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tray.log")


def _log(msg: str):
    """pythonw 无 stdout/stderr，日志必须落盘。"""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except OSError:
        pass


def _make_icon_image():
    """程序化生成托盘图标（蓝底日历+白勾），无需外部图片文件。"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 10, 60, 60], radius=10, fill=(30, 136, 229, 255))
    d.rectangle([4, 10, 60, 22], fill=(21, 101, 192, 255))     # 日历头部
    d.rectangle([16, 4, 22, 14], fill=(21, 101, 192, 255))     # 左侧日历环
    d.rectangle([42, 4, 48, 14], fill=(21, 101, 192, 255))     # 右侧日历环
    d.line([(20, 42), (29, 51), (46, 32)], fill=(255, 255, 255, 255), width=6)  # 勾
    return img


def _open_page(icon=None, item=None):
    webbrowser.open(URL)


def _quit(icon, item):
    icon.stop()
    # Gradio 的工作线程非守护线程，直接终止进程最干净
    os._exit(0)


def _already_running() -> bool:
    """端口可连通说明已有实例在跑。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((HOST, PORT)) == 0


def _run_server():
    from datetime import datetime
    try:
        from app import build_app
        build_app().launch(
            server_name=HOST, server_port=PORT, share=False,
            inbrowser=True,          # 服务就绪后自动打开默认浏览器
            prevent_thread_lock=True,  # 不阻塞主线程，交给托盘事件循环
            quiet=True,
        )
    except Exception:
        _log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] server thread crashed:\n"
             + traceback.format_exc())


def main():
    if _already_running():
        webbrowser.open(URL)
        sys.exit(0)

    # pythonw 下 stdout/stderr 为 None：uvicorn 日志初始化会调 sys.stdout.isatty()，
    # 直接 None 会崩（这就是之前双击 start.bat 拒绝连接的根因），必须替换成完整哑对象
    class _NullIO:
        def write(self, *a): return 0
        def flush(self): pass
        def isatty(self): return False
        def close(self): pass
        @property
        def encoding(self): return "utf-8"
        @property
        def errors(self): return "replace"
        def fileno(self): raise OSError("no fileno")
    if sys.stdout is None: sys.stdout = _NullIO()
    if sys.stderr is None: sys.stderr = _NullIO()

    threading.Thread(target=_run_server, daemon=True).start()

    menu = pystray.Menu(
        pystray.MenuItem("打开周报页面", _open_page, default=True),  # 双击图标触发
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", _quit),
    )
    icon = pystray.Icon("WeeklyReportHelper", _make_icon_image(),
                        "Weekly Report Helper", menu)
    icon.run()  # 阻塞直到"退出"
    os._exit(0)


if __name__ == "__main__":
    main()
