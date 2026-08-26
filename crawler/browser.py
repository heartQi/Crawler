#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动 Chrome + 远程调试附着 — 用于拉勾/猎聘等强验证站点。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import List, Optional

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


def get_debugger_tabs(port: int = REMOTE_DEBUG_PORT) -> List[dict]:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/list", timeout=2,
        ) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []


def manual_browser_ready(
    platform_key: str,
    port: int = REMOTE_DEBUG_PORT,
    captcha_title_keywords: Optional[List[str]] = None,
) -> bool:
    """通过调试端口判断页面是否已离开验证页（无需 Selenium 附着）。"""
    captcha_title_keywords = captcha_title_keywords or []
    domain_map = {
        "lagou": "lagou.com",
        "liepin": "liepin.com",
    }
    domain = domain_map.get(platform_key, "")
    if not domain:
        return False

    for tab in get_debugger_tabs(port):
        url = tab.get("url", "")
        title = tab.get("title", "")
        if domain not in url:
            continue
        if any(kw in title for kw in captcha_title_keywords):
            return False
        if title and title not in ("", "about:blank"):
            if "访问验证" in title or "安全中心" in title:
                return False
            return True
    return False


def wait_manual_browser_ready(
    platform_key: str,
    captcha_title_keywords: Optional[List[str]] = None,
    timeout: float = 20.0,
    port: int = REMOTE_DEBUG_PORT,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manual_browser_ready(platform_key, port, captcha_title_keywords):
            return True
        time.sleep(0.5)
    return manual_browser_ready(platform_key, port, captcha_title_keywords)


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
