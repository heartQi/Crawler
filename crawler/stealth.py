#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""浏览器反自动化检测 — 隐藏 webdriver 特征与顶部控制提示。"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.chrome.webdriver import WebDriver

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 在 document 创建前注入，覆盖常见自动化探测点
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

if (!window.chrome) {
    window.chrome = {};
}
window.chrome.runtime = window.chrome.runtime || {};
window.chrome.loadTimes = window.chrome.loadTimes || function() {};
window.chrome.csi = window.chrome.csi || function() {};
window.chrome.app = window.chrome.app || {};

Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [
            {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
            {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
            {name: 'Native Client', filename: 'internal-nacl-plugin'},
        ];
        arr.item = (i) => arr[i];
        arr.namedItem = (n) => arr.find(p => p.name === n);
        arr.refresh = () => {};
        return arr;
    },
});

Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
});

Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
});

Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
});

Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
});

const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
"""


def apply_stealth(driver: "WebDriver") -> None:
    """通过 CDP 注入脚本并统一 User-Agent，降低被识别为自动化的概率。"""
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": STEALTH_JS},
    )
    driver.execute_cdp_cmd(
        "Network.setUserAgentOverride",
        {
            "userAgent": USER_AGENT,
            "acceptLanguage": "zh-CN,zh;q=0.9,en;q=0.8",
            "platform": "Win32",
        },
    )


def human_pause(min_s: float = 0.8, max_s: float = 2.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def warm_up_lagou(driver: "WebDriver", stop_check=None) -> None:
    """拉勾：先访问首页建立正常会话，再进入搜索页。"""
    if stop_check and stop_check():
        return
    driver.get("https://www.lagou.com/")
    human_pause(2.0, 3.5)
    gentle_scroll(driver, stop_check)
    human_pause(0.8, 1.6)


def gentle_scroll(driver: "WebDriver", stop_check=None) -> None:
    """模拟人工滚动，触发懒加载并降低“机器直跳”特征。"""
    for ratio in (0.25, 0.55, 0.85):
        if stop_check and stop_check():
            return
        driver.execute_script(
            "window.scrollTo({top: document.body.scrollHeight * arguments[0], behavior: 'smooth'});",
            ratio,
        )
        time.sleep(random.uniform(0.4, 0.9))
