#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从本地 .credentials.json 读取各平台登录账号（该文件不提交 git）。"""

from __future__ import annotations

import json
import os
from typing import Optional

from .auth import Credentials
from .config import CREDENTIALS_FILE

PLATFORM_ALIASES = {
    "boss": ("boss", "zhipin", "boss直聘"),
    "lagou": ("lagou", "拉勾", "拉勾网"),
    "liepin": ("liepin", "猎聘"),
    "zhilian": ("zhilian", "智联", "智联招聘"),
    "51job": ("51job", "前程无忧", "job51"),
}


def load_all_accounts(path: str = CREDENTIALS_FILE) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _pick_account(raw: dict, platform_key: str) -> dict:
    if not isinstance(raw, dict):
        return {}
    keys = PLATFORM_ALIASES.get(platform_key, (platform_key,))
    for key in keys:
        item = raw.get(key)
        if isinstance(item, dict):
            return item
    accounts = raw.get("accounts")
    if isinstance(accounts, dict):
        for key in keys:
            item = accounts.get(key)
            if isinstance(item, dict):
                return item
    return {}


def load_platform_credentials(
    platform_key: str,
    path: str = CREDENTIALS_FILE,
) -> Optional[Credentials]:
    """按平台读取用户名/密码；未配置则返回 None。"""
    item = _pick_account(load_all_accounts(path), platform_key)
    username = str(item.get("username") or item.get("account") or item.get("phone") or "").strip()
    password = str(item.get("password") or "")
    if not username and not password:
        return None
    return Credentials(username=username, password=password)


def load_platform_login_url(
    platform_key: str,
    path: str = CREDENTIALS_FILE,
) -> str:
    defaults = {
        "boss": "https://www.zhipin.com/web/user/?ka=header-login",
        "lagou": "https://passport.lagou.com/login/login.html",
        "liepin": "https://passport.liepin.com/account/login/",
        "zhilian": "https://passport.zhaopin.com/login",
        "51job": "https://login.51job.com",
    }
    item = _pick_account(load_all_accounts(path), platform_key)
    return str(item.get("url") or defaults.get(platform_key, "")).strip()


def resolve_credentials(
    platform_key: str,
    credentials: Optional[Credentials] = None,
) -> Optional[Credentials]:
    """优先使用调用方传入的凭据，否则读本地配置文件。"""
    if credentials and (credentials.username or credentials.password):
        return credentials
    return load_platform_credentials(platform_key)
