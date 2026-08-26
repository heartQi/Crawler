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
from .browser import (
    attach_to_chrome,
    is_debug_port_open,
    launch_manual_chrome,
    wait_manual_browser_ready,
)
from .config import (
    BROWSER_HEADLESS,
    BROWSER_PROFILE_DIR,
    ELEMENT_WAIT_TIMEOUT,
    HUMAN_DELAY_RANGE,
    MAX_PAGES,
    PAGE_LOAD_TIMEOUT,
    PLATFORMS,
    REMOTE_CHROME_PLATFORMS,
    CRAWL_BLOCKED,
    CRAWL_OK,
)
from .cookie import CookieManager
from .models import CompanyInfo, CrawlResult
from .parsers import PLATFORM_CONFIG
from .stealth import USER_AGENT, apply_stealth, gentle_scroll, human_pause

MANUAL_START_URLS = {
    "lagou": "https://www.lagou.com/",
    "liepin": "https://www.liepin.com/",
}

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


def _build_chrome_options(headless: bool = BROWSER_HEADLESS) -> Options:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,900")
    opts.add_argument(f"--user-data-dir={BROWSER_PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_experimental_option(
        "prefs",
        {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        },
    )
    opts.add_argument(f"user-agent={USER_AGENT}")
    return opts


def _finalize_driver(driver: webdriver.Chrome) -> webdriver.Chrome:
    """标准 Selenium 驱动注入 stealth；uc 驱动请勿调用。"""
    apply_stealth(driver)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


def _create_driver(headless: bool = BROWSER_HEADLESS) -> webdriver.Chrome:
    """优先 undetected-chromedriver（隐藏顶部自动化提示），失败则回退标准 Selenium。"""
    # 1: undetected-chromedriver — 内置反检测，不再叠加 CDP stealth（会干扰滑块验证）
    try:
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1440,900")
        options.add_argument("--disable-infobars")
        options.add_argument(f"user-agent={USER_AGENT}")

        driver = uc.Chrome(
            options=options,
            user_data_dir=BROWSER_PROFILE_DIR,
            headless=headless,
            use_subprocess=True,
        )
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        return driver
    except ImportError:
        pass
    except Exception:
        pass

    opts = _build_chrome_options(headless)

    # 2: webdriver-manager
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        svc = ChromeDriverManager().install()
        driver = webdriver.Chrome(service=Service(svc), options=opts)
        return _finalize_driver(driver)
    except ImportError:
        pass
    except Exception:
        pass

    # 3: local chromedriver
    cd_path = _detect_chromedriver_path()
    if cd_path:
        try:
            svc = Service(executable_path=cd_path)
            driver = webdriver.Chrome(service=svc, options=opts)
            return _finalize_driver(driver)
        except Exception:
            pass

    # 4: Selenium Manager (Selenium 4.6+)
    try:
        driver = webdriver.Chrome(options=opts)
        return _finalize_driver(driver)
    except Exception as e:
        raise RuntimeError(
            f"无法创建 Chrome WebDriver: {e}\n"
            "请确认已安装 Google Chrome，且没有其他进程占用项目浏览器配置。\n"
            "也可以执行：pip install undetected-chromedriver webdriver-manager"
        ) from e


class CrawlerEngine:
    """使用一个可见浏览器会话顺序采集多个平台。"""

    def __init__(self, headless: bool = BROWSER_HEADLESS):
        self.cookie_mgr = CookieManager()
        self._platforms = list(PLATFORM_CONFIG.keys())
        self._driver: Optional[webdriver.Chrome] = None
        self._driver_mode: Optional[str] = None  # "auto" | "attach"
        self.headless = headless

    def _reset_driver(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
        self._driver = None
        self._driver_mode = None

    def _ensure_driver(
        self,
        platform_key: str,
        login_confirmation,
        log_callback: Callable[[str], None],
        pname: str,
    ) -> webdriver.Chrome:
        """强验证平台用普通 Chrome + 调试端口附着，其它平台用自动化驱动。"""
        if platform_key in REMOTE_CHROME_PLATFORMS:
            if self._driver_mode != "attach":
                self._reset_driver()
                start_url = MANUAL_START_URLS.get(platform_key, "about:blank")
                log_callback(
                    f"[{pname}] 正在打开普通 Chrome（无自动化控制条），"
                    f"请在该窗口手动完成验证..."
                )
                if not is_debug_port_open():
                    launch_manual_chrome(start_url=start_url)
                else:
                    log_callback(f"[{pname}] 检测到已有调试 Chrome，直接连接...")

                cfg = PLATFORM_CONFIG.get(platform_key, {})
                captcha_titles = cfg.get("captcha_title_keywords", [])
                log_callback(f"[{pname}] 等待页面加载...")
                if wait_manual_browser_ready(
                    platform_key, captcha_titles, timeout=18.0,
                ):
                    log_callback(f"[{pname}] 页面已就绪，自动继续查询...")
                else:
                    log_callback(
                        f"[{pname}] 需要手动确认：请在主程序弹窗点击「已完成」继续"
                    )
                    if not login_confirmation:
                        raise RuntimeError(f"{pname} 需要手动验证，但程序未提供确认回调")
                    if not login_confirmation(pname, 300):
                        raise RuntimeError(f"{pname} 未完成手动验证")

                self._driver = attach_to_chrome()
                self._driver_mode = "attach"
                log_callback(f"[{pname}] 已连接浏览器，开始查询...")
            return self._driver

        if self._driver_mode == "attach":
            self._reset_driver()
        if self._driver is None:
            self._driver = _create_driver(self.headless)
            self._driver_mode = "auto"
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

        try:
            try:
                driver = self._ensure_driver(
                    platform_key, login_confirmation, log_callback, pname,
                )
            except RuntimeError as exc:
                return CrawlResult([], CRAWL_BLOCKED, str(exc))

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
            human_pause(2.0, 3.5)

            if not self._resolve_captcha_page(
                driver, cfg, pname, first_url, login_confirmation,
                log_callback, stop_check,
            ):
                return CrawlResult(
                    [],
                    CRAWL_BLOCKED,
                    f"{pname} 验证未通过。页面标题：{driver.title}",
                )

            last_signature = None
            completed_pages = 0
            for page in range(1, MAX_PAGES + 1):
                if event.is_set() or stop_check():
                    return CrawlResult(results, CRAWL_OK, f"用户中止，已获取 {len(results)} 条")

                items = self._wait_for_items(driver, cfg)
                if not items and self._detect_captcha(driver, cfg, log_callback):
                    log_callback(f"[{pname}] 第 {page} 页仍被验证拦截，请再次完成验证...")
                    if self._resolve_captcha_page(
                        driver, cfg, pname, first_url, login_confirmation,
                        log_callback, stop_check,
                    ):
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
            log_callback(f"[{pname}] 查询异常：{exc}")
            return CrawlResult([], CRAWL_BLOCKED, f"{pname} 查询异常：{exc}")
        finally:
            if credentials is not None:
                credentials.clear()

    @staticmethod
    def _detect_captcha(driver, cfg, log_callback=None) -> bool:
        """检测是否处于验证/安全拦截页（避免误匹配页面脚本中的关键字）。"""
        time.sleep(0.4)
        title = driver.title or ""

        for kw in cfg.get("captcha_title_keywords", []):
            if kw in title:
                if log_callback:
                    log_callback(f"[验证检测] 标题匹配 '{kw}'")
                return True

        captcha_css = cfg.get("captcha_css", "")
        if captcha_css:
            try:
                if driver.find_elements(By.CSS_SELECTOR, captcha_css):
                    if log_callback:
                        log_callback("[验证检测] 发现验证组件")
                    return True
            except WebDriverException:
                pass

        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            for kw in cfg.get("captcha_body_keywords", []):
                if kw in body_text:
                    if log_callback:
                        log_callback(f"[验证检测] 页面内容匹配 '{kw}'")
                    return True
        except WebDriverException:
            pass
        return False

    def _resolve_captcha_page(
        self,
        driver,
        cfg,
        pname: str,
        target_url: str,
        login_confirmation,
        log_callback,
        stop_check,
    ) -> bool:
        """等待用户手动完成验证，支持刷新后重试。"""
        if not self._detect_captcha(driver, cfg, log_callback):
            return True
        if not login_confirmation:
            return False

        wait_sec = 180 if (
            cfg.get("captcha_keywords")
            or cfg.get("captcha_body_keywords")
            or cfg.get("captcha_title_keywords")
        ) else 120
        max_rounds = 5
        for round_i in range(max_rounds):
            if stop_check():
                return False
            if not self._detect_captcha(driver, cfg):
                log_callback(f"[{pname}] 验证已通过，继续查询...")
                return True

            if round_i == 0:
                log_callback(
                    f"[{pname}] 检测到验证页，请在浏览器中完成滑块/验证；"
                    f"若提示失败请先点刷新再重试"
                )
            else:
                log_callback(f"[{pname}] 验证仍未通过（第 {round_i + 1}/{max_rounds} 次）...")

            if not login_confirmation(pname, wait_sec):
                return False

            human_pause(1.0, 2.0)
            try:
                driver.refresh()
            except WebDriverException:
                driver.get(target_url)
            human_pause(2.5, 4.0)

        return not self._detect_captcha(driver, cfg, log_callback)

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
        gentle_scroll(driver, stop_check=event.is_set)

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
        self._reset_driver()
