#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动 Chrome + 远程调试附着 — 用于拉勾/猎聘等强验证站点。"""

from __future__ import annotations

import json
import os
import random
import socket
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, List, Optional

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from .config import MANUAL_BROWSER_PROFILE_DIR, REMOTE_DEBUG_PORT

ATTACHED_PAGE_LOAD_TIMEOUT = 30
ATTACH_TIMEOUT = 25

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
    proxy_server: str = "",
) -> None:
    """启动普通 Chrome（非 WebDriver），供用户手动完成验证。"""
    chrome = find_chrome_executable()
    if not chrome:
        raise RuntimeError("未找到 Google Chrome，请先安装 Chrome 浏览器。")

    os.makedirs(profile_dir, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if proxy_server:
        args.append(f"--proxy-server={proxy_server}")
    args.append(start_url)
    subprocess.Popen(
        args,
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
        if platform_key == "liepin":
            u = url.lower()
            if "wow.liepin" in u:
                continue
            if "passport.liepin" in u or "account.liepin" in u:
                continue
            if "liepin.com" in u and ("login" in u or "signin" in u):
                continue
            if title == "登录" or ("登录" in title and "猎聘" in title):
                continue
        if platform_key == "lagou":
            u = url.lower()
            if "passport.lagou" in u or "/login" in u:
                continue
            block_titles = tuple(captcha_title_keywords) + (
                "访问验证", "安全验证", "人机验证", "验证中心",
            )
            if any(kw in title for kw in block_titles):
                return False
            if "lagou.com" in u and title and title not in ("", "about:blank"):
                return True
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


def _create_attached_driver(port: int) -> webdriver.Chrome:
    opts = Options()
    opts.page_load_strategy = "eager"
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)
    except Exception:
        return webdriver.Chrome(options=opts)


def focus_platform_tab(driver, domain: str) -> bool:
    """切换到目标平台标签页。"""
    try:
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            try:
                if domain in (driver.current_url or ""):
                    return True
            except WebDriverException:
                continue
    except WebDriverException:
        pass
    return False


def attach_to_chrome(
    port: int = REMOTE_DEBUG_PORT,
    platform_domain: str = "",
    log: Optional[Callable[[str], None]] = None,
) -> webdriver.Chrome:
    """附着到已打开的 Chrome，不再由 WebDriver 启动浏览器。"""
    if not is_debug_port_open(port):
        raise RuntimeError(
            f"未检测到调试端口 {port} 上的 Chrome。\n"
            "请先在弹出的浏览器窗口中完成验证。"
        )

    if log:
        log("正在连接 Chrome 调试端口（首次可能需十几秒）...")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_create_attached_driver, port)
        try:
            driver = future.result(timeout=ATTACH_TIMEOUT)
        except FuturesTimeoutError as exc:
            raise RuntimeError(
                f"连接 Chrome 超时（{ATTACH_TIMEOUT} 秒）。\n"
                "请关闭所有 Chrome 窗口后重试，或删除项目下的 .manual_browser 文件夹。"
            ) from exc

    driver.set_page_load_timeout(ATTACHED_PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(15)

    if platform_domain:
        if focus_platform_tab(driver, platform_domain):
            if log:
                log(f"已切换到 {platform_domain} 标签页")
        elif log:
            log(f"未找到 {platform_domain} 标签，使用当前标签页")

    if log:
        log("Chrome 连接成功")
    return driver


def safe_get(driver, url: str, log=None) -> None:
    """导航到 URL；超时则停止加载并继续（避免 SPA 永远等 complete）。"""
    try:
        driver.get(url)
    except TimeoutException:
        if log:
            log("页面加载超时，继续处理已加载内容…")
        try:
            driver.execute_script("window.stop();")
        except WebDriverException:
            pass
    time.sleep(random.uniform(1.5, 2.5))


def soft_navigate(driver, url: str, log=None) -> None:
    """用页面内跳转代替 driver.get，降低被识别为自动化的概率。"""
    if log:
        log(f"正在跳转: {url[:100]}...")
    try:
        driver.execute_script("window.location.assign(arguments[0]);", url)
    except WebDriverException:
        safe_get(driver, url, log)
        return
    time.sleep(random.uniform(2.0, 3.0))
    if log:
        try:
            log(f"跳转后: {(driver.current_url or '')[:90]} | {driver.title}")
        except WebDriverException:
            pass
