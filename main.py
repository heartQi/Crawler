#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
招聘平台公司信息爬虫 — 主入口

支持平台：
- Boss直聘 / 智联招聘 / 前程无忧 / 拉勾 / 猎聘

用法：
    python main.py
"""

import sys
import subprocess


def _ensure_deps():
    """检查并自动安装缺失依赖"""
    missing = []
    try:
        import selenium  # noqa: F401
    except ImportError:
        missing.append("selenium")
    try:
        import webdriver_manager  # noqa: F401
    except ImportError:
        missing.append("webdriver-manager")
    try:
        import undetected_chromedriver  # noqa: F401
    except ImportError:
        missing.append("undetected-chromedriver")

    if missing:
        print(f"正在安装缺失依赖: {', '.join(missing)} ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install"] + missing,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print("依赖安装完成！")


if __name__ == "__main__":
    _ensure_deps()

    from crawler.gui import CrawlerApp

    app = CrawlerApp()
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n用户退出")
    except Exception as e:
        print(f"\n程序异常: {e}")
        input("按 Enter 键退出...")