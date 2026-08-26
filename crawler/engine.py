#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爬虫引擎 — 多平台统一翻页框架."""

import os
import random
import shutil
import time
import urllib.parse
from threading import Event
from typing import Callable, List, Optional

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .auth import Credentials, LoginCoordinator
from .config import (
    BROWSER_HEADLESS,
    BROWSER_PROFILE_DIR,
    ELEMENT_WAIT_TIMEOUT,
    HUMAN_DELAY_RANGE,
    MAX_PAGES,
    PAGE_LOAD_TIMEOUT,
    PLATFORMS,
    CRAWL_BLOCKED,
    CRAWL_OK,
)
from .cookie import CookieManager
from .models import CompanyInfo, CrawlResult
from .parsers import PLATFORM_CONFIG

def _detect_chromedriver_path() -> Optional[str]:
    path = shutil.which("chromedriver")
    if path:
        return path
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chromedriver.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chromedriver.exe",
        r"C:\chromedriver.exe",
    ]:
        if os.path.exists(p):
            return p
    for p in [
        "/usr/local/bin/chromedriver",
        "/opt/homebrew/bin/chromedriver",
        "/usr/bin/chromedriver",
    ]:
        if os.path.exists(p):
            return p
    return None


def _create_driver(headless: bool = BROWSER_HEADLESS) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,900")
    opts.add_argument(f"--user-data-dir={BROWSER_PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    opts.add_experimental_option(
        "prefs",
        {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        },
    )
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    # 1: webdriver-manager
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        svc = ChromeDriverManager().install()
        driver = webdriver.Chrome(service=Service(svc), options=opts)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        return driver
    except ImportError:
        pass
    except Exception:
        pass

    # 2: local chromedriver
    cd_path = _detect_chromedriver_path()
    if cd_path:
        try:
            svc = Service(executable_path=cd_path)
            driver = webdriver.Chrome(service=svc, options=opts)
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            return driver
        except Exception:
            pass

    # 3: Selenium Manager (Selenium 4.6+)
    try:
        driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        return driver
    except Exception as e:
        raise RuntimeError(
            f"无法创建 Chrome WebDriver: {e}\n"
            "请确认已安装 Google Chrome，且没有其他进程占用项目浏览器配置。\n"
            "也可以执行：pip install webdriver-manager"
        ) from e


class CrawlerEngine:
    """使用一个可见浏览器会话顺序采集多个平台。"""

    def __init__(self, headless: bool = BROWSER_HEADLESS):
        self.cookie_mgr = CookieManager()
        self._platforms = list(PLATFORM_CONFIG.keys())
        self._driver: Optional[webdriver.Chrome] = None
        self.headless = headless

    def _get_driver(self) -> webdriver.Chrome:
        if self._driver is None:
            self._driver = _create_driver(self.headless)
        return self._driver

    def crawl(
        self,
        platform_key: str,
        keyword: str,
        count: int = 0,
        city_code: str = "",
        stop_check: Callable[[], bool] = lambda: False,
        log_callback: Callable[[str], None] = print,
        stop_event: Optional[Event] = None,
        page_callback: Optional[Callable[[str, int, List[CompanyInfo], int], None]] = None,
        credentials: Optional[Credentials] = None,
        login_confirmation: Optional[Callable[[str, int], bool]] = None,
    ) -> CrawlResult:
        if platform_key not in PLATFORM_CONFIG:
            return CrawlResult([], CRAWL_BLOCKED, f"未知平台: {platform_key}")

        event = stop_event or Event()
        cfg = PLATFORM_CONFIG[platform_key]
        pname = PLATFORMS[platform_key]["name"]
        results: List[CompanyInfo] = []
        seen = set()
        driver = self._get_driver()

        try:
            if cfg.get("requires_login"):
                auth = LoginCoordinator(driver, event, log_callback)
                if not auth.ensure_boss_login(credentials, login_confirmation):
                    message = "登录未完成或登录状态校验失败"
                    return CrawlResult([], CRAWL_BLOCKED, f"{pname}: {message}")

            first_url = cfg["url_tpl"].format(
                kw=urllib.parse.quote(keyword),
                city=city_code,
                page=1,
            )
            driver.get(first_url)

            last_signature = None
            completed_pages = 0
            for page in range(1, MAX_PAGES + 1):
                if event.is_set() or stop_check():
                    return CrawlResult(results, CRAWL_OK, f"用户中止，已获取 {len(results)} 条")

                items = self._wait_for_items(driver, cfg)
                if not items:
                    if self._has_empty_state(driver, cfg):
                        log_callback(f"[{pname}] 第 {page} 页没有结果")
                    else:
                        log_callback(f"[{pname}] 第 {page} 页未找到职位卡片，选择器可能已变化")
                    break

                self._scroll_for_lazy_load(driver, event)
                items = driver.find_elements(By.CSS_SELECTOR, cfg["item_css"])
                signature = self._page_signature(items)
                if signature and signature == last_signature:
                    log_callback(f"[{pname}] 检测到重复页面，停止翻页")
                    break
                last_signature = signature

                page_data = self._parse_page(items, cfg, seen)
                results.extend(page_data)
                completed_pages = page
                log_callback(
                    f"[{pname}] 第 {page} 页新增 {len(page_data)} 条，累计 {len(results)} 条"
                )
                if page_callback:
                    page_callback(pname, page, page_data, len(results))
                if count > 0 and len(results) >= count:
                    results = results[:count]
                    break
                if page >= MAX_PAGES or not self._go_next_page(driver, cfg, page, keyword, city_code, event):
                    break

            if results:
                return CrawlResult(
                    results,
                    CRAWL_OK,
                    f"成功获取 {len(results)} 条（共 {completed_pages} 页）",
                )
            return CrawlResult(
                [],
                CRAWL_BLOCKED,
                f"{pname} 页面已打开，但未提取到数据。页面标题：{driver.title}",
            )
        except Exception as exc:
            log_callback(f"[{pname}] 采集异常：{exc}")
            return CrawlResult([], CRAWL_BLOCKED, f"{pname} 采集异常：{exc}")
        finally:
            if credentials is not None:
                credentials.clear()

    def _wait_for_items(self, driver, cfg):
        try:
            WebDriverWait(driver, ELEMENT_WAIT_TIMEOUT).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, cfg["item_css"])
                or self._has_empty_state(d, cfg)
            )
        except TimeoutException:
            return []
        return driver.find_elements(By.CSS_SELECTOR, cfg["item_css"])

    @staticmethod
    def _has_empty_state(driver, cfg) -> bool:
        empty_css = cfg.get("empty_css")
        return bool(empty_css and driver.find_elements(By.CSS_SELECTOR, empty_css))

    def _scroll_for_lazy_load(self, driver, event: Event) -> None:
        for ratio in (0.35, 0.7, 1.0):
            if event.is_set():
                return
            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight * arguments[0]);",
                ratio,
            )
            self._interruptible_delay(event)

    @staticmethod
    def _parse_page(items, cfg, seen) -> List[CompanyInfo]:
        page_data = []
        for item in items:
            try:
                info = cfg["parse_fn"](item)
                if not info:
                    continue
                key = (info.name, info.hot_jobs, info.location)
                if key in seen:
                    continue
                seen.add(key)
                page_data.append(info)
            except (StaleElementReferenceException, WebDriverException):
                continue
        return page_data

    @staticmethod
    def _page_signature(items):
        signatures = []
        for item in items[:3]:
            try:
                signatures.append(item.text[:120])
            except StaleElementReferenceException:
                continue
        return tuple(signatures)

    def _go_next_page(self, driver, cfg, page, keyword, city_code, event: Event) -> bool:
        if event.is_set():
            return False
        old_url = driver.current_url
        old_items = driver.find_elements(By.CSS_SELECTOR, cfg["item_css"])
        old_first = old_items[0] if old_items else None
        old_signature = self._page_signature(old_items)
        next_elements = driver.find_elements(By.CSS_SELECTOR, cfg.get("next_css", ""))
        next_button = next((el for el in next_elements if el.is_displayed() and el.is_enabled()), None)

        if next_button is not None:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
            self._interruptible_delay(event)
            try:
                next_button.click()
            except WebDriverException:
                driver.execute_script("arguments[0].click();", next_button)
            try:
                WebDriverWait(driver, ELEMENT_WAIT_TIMEOUT).until(
                    lambda d: d.current_url != old_url
                    or (old_first is not None and EC.staleness_of(old_first)(d))
                    or self._page_signature(
                        d.find_elements(By.CSS_SELECTOR, cfg["item_css"])
                    ) != old_signature
                )
            except TimeoutException:
                return False
            return True

        # 没有可点击控件时，使用平台 URL 页码作为兼容回退。
        fallback = cfg["url_tpl"].format(
            kw=urllib.parse.quote(keyword),
            city=city_code,
            page=page + 1,
        )
        if fallback == old_url:
            return False
        driver.get(fallback)
        return True

    @staticmethod
    def _interruptible_delay(event: Event) -> None:
        event.wait(random.uniform(*HUMAN_DELAY_RANGE))

    def close(self):
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
