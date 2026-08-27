#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可见浏览器登录协调，不绕过验证码或短信验证。"""

import time
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
        "li[data-type='pwd']",
        ".btn-sign-switch",
        "a[href*='password']",
    )
    LOGIN_BUTTON_SELECTORS = (
        "button[type='submit']",
        "button.btn-sign",
        ".btn-sign",
        "button.login-btn",
        ".login-btn",
        "button[ka*='login']",
        "input[type='submit']",
        "button.ant-btn-primary",
    )
    AUTHENTICATED_SELECTORS = (
        ".nav-figure",
        ".user-nav",
        "[class*='user-avatar']",
        ".job-card-wrapper",
    )
    LIEPIN_LOGIN_URL = "https://passport.liepin.com/account/login/"
    LIEPIN_AUTH_SELECTORS = (
        ".header-quick-menu",
        "[class*='header-user']",
        ".user-name",
        ".nav-user-name",
        "[class*='user-avatar']",
    )
    LIEPIN_PASSWORD_LINK_XPATHS = (
        "//a[contains(text(),'已有账号')]",
        "//a[contains(text(),'直接登录')]",
        "//span[contains(text(),'密码登录')]",
        "//*[contains(text(),'账号密码登录')]",
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
        """打开 Boss 登录页，从配置预填并尝试提交，验证码仍需人工完成。"""
        from .accounts import resolve_credentials

        credentials = resolve_credentials("boss", credentials)
        self.driver.get("https://www.zhipin.com/")
        self._wait_document()
        if self.is_boss_authenticated():
            self.log("[Boss直聘] 已复用浏览器登录会话")
            return True

        self.driver.get(self.BOSS_LOGIN_URL)
        self._wait_document()
        submitted = self._prefill_and_submit(credentials, "Boss直聘")
        if submitted:
            time.sleep(2.0)
            self._wait_document()
            if self.is_boss_authenticated():
                self.log("[Boss直聘] 已自动登录")
                return True
            self.log("[Boss直聘] 账号已填写并提交，若出现短信/滑块请在浏览器完成")

        if confirmation is None:
            return self.is_boss_authenticated()
        if not confirmation("Boss直聘", LOGIN_WAIT_TIMEOUT):
            return False
        if self.stop_event.is_set():
            return False

        self._wait_document()
        authenticated = self.is_boss_authenticated()
        if not authenticated:
            self.log("[Boss直聘] 未检测到有效登录状态")
        return authenticated

    def ensure_liepin_login(
        self,
        credentials: Optional[Credentials],
        confirmation: Optional[Callable[[str, int], bool]],
    ) -> bool:
        """猎聘：wow/通行证页填写账号并尝试登录，短信验证码仍需人工完成。"""
        from .accounts import load_platform_login_url, resolve_credentials

        credentials = resolve_credentials("liepin", credentials)
        if self.is_liepin_authenticated():
            self.log("[猎聘] 已登录")
            return True

        current = (self.driver.current_url or "").lower()
        if self._is_liepin_blocked_url(current):
            self._switch_liepin_password_login()
            time.sleep(1.0)
            if not self._is_liepin_blocked_url(self.driver.current_url or ""):
                self._wait_document()
            else:
                login_url = load_platform_login_url("liepin") or self.LIEPIN_LOGIN_URL
                self.driver.get(login_url)
                self._wait_document()
                self._switch_liepin_password_login()
        else:
            login_url = load_platform_login_url("liepin") or self.LIEPIN_LOGIN_URL
            self.driver.get(login_url)
            self._wait_document()
            self._switch_liepin_password_login()

        submitted = self._prefill_and_submit(credentials, "猎聘")
        if submitted:
            time.sleep(2.5)
            self._wait_document()
            if self.is_liepin_authenticated():
                self.log("[猎聘] 已自动登录")
                self._go_liepin_home_after_login()
                return True
            self.log("[猎聘] 账号已提交，若需短信验证码请在浏览器完成")

        if confirmation is None:
            return self.is_liepin_authenticated()
        if not confirmation("猎聘", LOGIN_WAIT_TIMEOUT):
            return False
        if self.stop_event.is_set():
            return False

        self._wait_document()
        authenticated = self.is_liepin_authenticated()
        if authenticated:
            self._go_liepin_home_after_login()
        elif not authenticated:
            self.log("[猎聘] 未检测到有效登录状态")
        return authenticated

    def _go_liepin_home_after_login(self) -> None:
        url = (self.driver.current_url or "").lower()
        if "www.liepin.com" in url and not self._is_liepin_blocked_url(url):
            return
        try:
            self.driver.get("https://www.liepin.com")
            self._wait_document()
        except WebDriverException:
            pass

    def is_liepin_authenticated(self) -> bool:
        current_url = (self.driver.current_url or "").lower()
        if self._is_liepin_blocked_url(current_url):
            return False
        for selector in self.LIEPIN_AUTH_SELECTORS:
            try:
                if self.driver.find_elements(By.CSS_SELECTOR, selector):
                    return True
            except WebDriverException:
                continue
        try:
            for cookie in self.driver.get_cookies():
                name = (cookie.get("name") or "").lower()
                if name in ("unique_key", "lt_auth", "liepin_login_valid"):
                    return True
        except WebDriverException:
            pass
        return "www.liepin.com" in current_url and "login" not in current_url

    def _is_liepin_blocked_url(self, url: str) -> bool:
        u = (url or "").lower()
        if "wow.liepin" in u or "passport.liepin" in u or "account.liepin" in u:
            return True
        return "liepin.com" in u and ("login" in u or "signin" in u)

    def _switch_liepin_password_login(self) -> bool:
        for xpath in self.LIEPIN_PASSWORD_LINK_XPATHS:
            try:
                for el in self.driver.find_elements(By.XPATH, xpath):
                    if el.is_displayed():
                        el.click()
                        return True
            except WebDriverException:
                continue
        return self._click_first(self.PASSWORD_TAB_SELECTORS)

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

    def _prefill_and_submit(
        self,
        credentials: Optional[Credentials],
        platform_name: str,
    ) -> bool:
        if credentials is None or not (credentials.username or credentials.password):
            self.log(f"[{platform_name}] 未配置账号，请填写 .credentials.json 或手动登录")
            return False
        self._click_first(self.PASSWORD_TAB_SELECTORS)
        time.sleep(0.4)
        filled = False
        if credentials.username:
            filled = self._fill_first(self.USERNAME_SELECTORS, credentials.username) or filled
        if credentials.password:
            filled = self._fill_first(self.PASSWORD_SELECTORS, credentials.password) or filled
        if not filled:
            self.log(f"[{platform_name}] 未找到登录输入框，请在浏览器中手动登录")
            return False
        self.log(f"[{platform_name}] 已从配置文件填写账号")
        if self._click_first(self.LOGIN_BUTTON_SELECTORS):
            self.log(f"[{platform_name}] 已点击登录")
            return True
        self.log(f"[{platform_name}] 已填写账号，请在浏览器中点击登录")
        return True

    def _prefill_boss(self, credentials: Optional[Credentials]) -> None:
        self._prefill_and_submit(credentials, "Boss直聘")

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
