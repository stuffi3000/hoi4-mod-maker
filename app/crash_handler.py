"""
全局崩溃处理器 — 捕获未处理异常, 弹窗显示原因 + 写 crash log 文件.

用法: 在 main.py 里 `install_crash_handler()` 之后再创建 QApplication.
所有未被 try/except 包住的异常都会触发崩溃对话框和 log 记录.
"""

from __future__ import annotations

import datetime
import os
import sys
import traceback
from pathlib import Path


def _write_crash_log(tb_text: str) -> str:
    """把 traceback 写到 logs/crash_YYYYMMDD_HHMMSS.log, 返回文件路径."""
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"crash_{ts}.log"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Crash time: {datetime.datetime.now().isoformat()}\n")
        f.write(f"# Python: {sys.version}\n")
        f.write(f"# Platform: {sys.platform}\n\n")
        f.write(tb_text)
    return str(path)


def _show_crash_dialog(exc_type, exc_value, exc_tb) -> None:
    """用 QMessageBox 显示崩溃信息. 如果 Qt 还没初始化, 只打印到 stderr."""
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    # 写 log 文件
    try:
        log_path = _write_crash_log(tb_text)
    except Exception:
        log_path = "(Failed to write log file)"

    # 打印到终端 (如果有)
    print("=" * 60, file=sys.stderr)
    print("CRASH:", file=sys.stderr)
    print(tb_text, file=sys.stderr)
    print(f"Log: {log_path}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # 尝试弹 Qt 对话框
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            return  # Qt 还没起来, 只能打印

        # 简短摘要 (最后一行通常是异常类型和消息)
        last_line = tb_text.strip().split("\n")[-1]

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        from ui.i18n import tr
        box.setWindowTitle(tr("crash_title"))
        box.setText(tr("crash_message").format(last_line))
        box.setInformativeText(tr("crash_log_saved").format(log_path))
        box.setDetailedText(tb_text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec_()
    except Exception:
        # 弹窗本身失败, 不抛出
        pass


def install_crash_handler() -> None:
    """安装全局 sys.excepthook. 在 QApplication 构造前调用."""
    def _handler(exc_type, exc_value, exc_tb):
        # KeyboardInterrupt 走默认行为
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _show_crash_dialog(exc_type, exc_value, exc_tb)

    sys.excepthook = _handler
