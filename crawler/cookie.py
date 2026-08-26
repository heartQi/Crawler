#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cookie 持久化管理
"""

import json
import os
import time
from .config import COOKIE_FILE


class CookieManager:
    """Cookie 持久化管理"""

    def __init__(self, filepath: str = COOKIE_FILE):
        self.filepath = filepath
        self._store: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self._store = json.load(f)
            except Exception:
                self._store = {}

    def _save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._store, f, ensure_ascii=False, indent=2)

    def set_cookie_string(self, platform: str, cookie_str: str):
        """存储原始 Cookie 字符串（浏览器 F12 复制格式）"""
        self._store[platform] = cookie_str.strip()
        self._save()

    def get_cookie_string(self, platform: str) -> str:
        return self._store.get(platform, "")

    def has_cookie(self, platform: str) -> bool:
        return bool(self._store.get(platform, "").strip())

    def delete_cookie(self, platform: str):
        self._store.pop(platform, None)
        self._save()

    def inject_to_driver(self, driver, platform: str, domain: str) -> bool:
        """将 Cookie 注入到 Selenium WebDriver（使用 CDP 方式避免 add_cookie 限制）"""
        cookie_str = self.get_cookie_string(platform)
        if not cookie_str:
            return False

        # 先访问目标域名，使 Cookie 域可写
        try:
            driver.get(domain)
            time.sleep(1)
        except Exception:
            pass

        # 方式 1: 先用 execute_cdp_cmd 批量注入（支持 HttpOnly、SameSite 等）
        try:
            driver.execute_cdp_cmd("Network.enable", {})
            for pair in cookie_str.split(";"):
                pair = pair.strip()
                if "=" not in pair:
                    continue
                name, value = pair.split("=", 1)
                driver.execute_cdp_cmd("Network.setCookie", {
                    "domain": domain.split("//")[-1].split("/")[0],
                    "path": "/",
                    "name": name.strip(),
                    "value": value.strip(),
                    "httpOnly": False,
                    "secure": domain.startswith("https"),
                })
            return True
        except Exception:
            pass

        # 方式 2: 降级为传统 add_cookie
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            try:
                driver.add_cookie({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": domain.split("//")[-1].split("/")[0],
                    "path": "/",
                })
            except Exception:
                continue
        return True