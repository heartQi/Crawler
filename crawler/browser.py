#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动 Chrome + 远程调试附着 — 用于拉勾/猎聘等强验证站点。"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from .config import MANUAL_BROWSER_PROFILE_DIR, PAGE_LOAD_TIMEOUT, REMOTE_DEBUG_PORT

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
]


def find_chrome_executable() -> Optional[str]:
    for path in CHROME_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


def is_debug_port_open(port: int = REMOTE_DEBUG_PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def launch_manual_chrome(
    start_url: str = "https://www.lagou.com/",
    port: int = REMOTE_DEBUG_PORT,
    profile_dir: str = MANUAL_BROWSER_PROFILE_DIR,
) -> None:
    """启动普通 Chrome（非 WebDriver），供用户手动完成验证。"""
    chrome = find_chrome_executable()
    if not chrome:
        raise RuntimeError("未找到 Google Chrome，请先安装 Chrome 浏览器。")

    os.makedirs(profile_dir, exist_ok=True)
    subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            start_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

    for _ in range(40):
        if is_debug_port_open(port):
            return
        time.sleep(0.25)
    raise RuntimeError(
        f"Chrome 调试端口 {port} 未就绪。\n"
        "请关闭占用该端口的 Chrome 后重试，或重启电脑后再运行。"
    )


def attach_to_chrome(port: int = REMOTE_DEBUG_PORT) -> webdriver.Chrome:
    """附着到已打开的 Chrome，不再由 WebDriver 启动浏览器。"""
    if not is_debug_port_open(port):
        raise RuntimeError(
            f"未检测到调试端口 {port} 上的 Chrome。\n"
            "请先在弹出的浏览器窗口中完成验证。"
        )

    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver
