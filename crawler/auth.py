#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可见浏览器登录协调，不绕过验证码或短信验证。"""

from dataclasses import dataclass
from threading import Event
from typing import Callable, Optional

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .config import LOGIN_WAIT_TIMEOUT


@dataclass
class Credentials:
    """仅在当前进程内使用的临时凭据。"""

    username: str = ""
    password: str = ""

    def clear(self) -> None:
        self.username = ""
        self.password = ""


class LoginCoordinator:
    BOSS_LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"
    USERNAME_SELECTORS = (
        "input[type='tel']",
        "input[name='phone']",
        "input[placeholder*='手机号']",
        "input[placeholder*='账号']",
    )
    PASSWORD_SELECTORS = (
        "input[type='password']",
        "input[name='password']",
        "input[placeholder*='密码']",
    )
    PASSWORD_TAB_SELECTORS = (
        "[class*='password']",
        "button[data-type='password']",
        "span[ka*='password']",
    )
    AUTHENTICATED_SELECTORS = (
        ".nav-figure",
        ".user-nav",
        "[class*='user-avatar']",
        ".job-card-wrapper",
    )

    def __init__(self, driver, stop_event: Event, log: Callable[[str], None] = print):
        self.driver = driver
        self.stop_event = stop_event
        self.log = log

    def ensure_boss_login(
        self,
        credentials: Optional[Credentials],
        confirmation: Optional[Callable[[str, int], bool]],
    ) -> bool:
        """打开 Boss 登录页，预填可识别字段，并等待用户完成人工验证。"""
        self.driver.get("https://www.zhipin.com/")
        self._wait_document()
        if self.is_boss_authenticated():
            self.log("[Boss直聘] 已复用浏览器登录会话")
            return True

        self.driver.get(self.BOSS_LOGIN_URL)
        self._wait_document()
        self._prefill_boss(credentials)

        if confirmation is None:
            return False
        if not confirmation("Boss直聘", LOGIN_WAIT_TIMEOUT):
            return False
        if self.stop_event.is_set():
            return False

        self._wait_document()
        authenticated = self.is_boss_authenticated()
        if not authenticated:
            self.log("[Boss直聘] 未检测到有效登录状态")
        return authenticated

    def is_boss_authenticated(self) -> bool:
        current_url = (self.driver.current_url or "").lower()
        title = (self.driver.title or "").lower()
        if "login" in current_url or "登录" in title or "验证" in title:
            return False
        for selector in self.AUTHENTICATED_SELECTORS:
            try:
                if self.driver.find_elements(By.CSS_SELECTOR, selector):
                    return True
            except WebDriverException:
                continue
        return False

    def _prefill_boss(self, credentials: Optional[Credentials]) -> None:
        if credentials is None or not (credentials.username or credentials.password):
            return
        self._click_first(self.PASSWORD_TAB_SELECTORS)
        if credentials.username:
            self._fill_first(self.USERNAME_SELECTORS, credentials.username)
        if credentials.password:
            self._fill_first(self.PASSWORD_SELECTORS, credentials.password)
        self.log("[Boss直聘] 已预填可识别的账号字段，请在浏览器中完成登录")

    def _fill_first(self, selectors, value: str) -> bool:
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if not elements:
                    continue
                element = elements[0]
                element.clear()
                element.send_keys(value)
                return True
            except WebDriverException:
                continue
        return False

    def _click_first(self, selectors) -> bool:
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and elements[0].is_displayed():
                    elements[0].click()
                    return True
            except WebDriverException:
                continue
        return False

    def _wait_document(self) -> None:
        WebDriverWait(self.driver, 20).until(
            lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
        )
