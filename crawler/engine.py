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

from .accounts import load_platform_proxy, resolve_credentials
from .auth import Credentials, LoginCoordinator
from .browser import (
    attach_to_chrome,
    is_debug_port_open,
    launch_manual_chrome,
    safe_get,
    soft_navigate,
    wait_manual_browser_ready,
)
from .config import (
    BROWSER_HEADLESS,
    BROWSER_PROFILE_DIR,
    ELEMENT_WAIT_TIMEOUT,
    HUMAN_DELAY_RANGE,
    LAGOU_AJAX_MAX_RETRIES,
    MAX_PAGES,
    PAGE_LOAD_TIMEOUT,
    PLATFORMS,
    REMOTE_CHROME_PLATFORMS,
    CRAWL_BLOCKED,
    CRAWL_OK,
)
from .cookie import CookieManager
from .models import CompanyInfo, CrawlResult
from .lagou_api import (
    build_list_url,
    build_lagou_company_lookup,
    build_wn_search_url,
    enrich_lagou_companies,
    extract_lagou_ajax_result,
    fetch_lagou_page_with_retry,
    format_lagou_error,
    is_lagou_search_url,
    is_lagou_waf_page,
    lagou_backoff_wait,
    lagou_prepare_ajax_page,
    lagou_referer_for_page,
    lagou_simulate_browse,
    navigate_to_lagou_search,
    parse_lagou_positions,
    resolve_lagou_referer,
)
from .lagou_company import fill_contacts_from_company_pages
from .liepin_api import (
    build_liepin_list_url,
    collect_liepin_page_data,
    ensure_liepin_home_tab,
    ensure_liepin_session,
    extract_jobs_from_dom,
    fetch_liepin_page_with_retry,
    format_liepin_error,
    install_liepin_capture_hook,
    is_liepin_success,
    navigate_to_liepin_search,
    parse_liepin_positions,
)
from .lagou_pager import (
    find_current_page_lagou_items,
    go_next_lagou_page,
    go_to_lagou_page,
    lagou_has_pager,
    lagou_position_signature,
    read_lagou_current_page,
    read_lagou_total_pages,
    sync_lagou_page_from_browser,
)
from .pacing import reset_pacer
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
    opts.page_load_strategy = "eager"
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
        options.page_load_strategy = "eager"
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
        self._attached_platform: Optional[str] = None
        self.headless = headless

    def _reset_driver(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
        self._driver = None
        self._driver_mode = None
        self._attached_platform = None

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
                    f"请在该窗口完成验证（猎聘无需登录）..."
                    if platform_key == "liepin"
                    else f"[{pname}] 正在打开普通 Chrome（无自动化控制条），"
                    f"请在该窗口手动完成验证..."
                )
                if not is_debug_port_open():
                    proxy = load_platform_proxy(platform_key)
                    launch_manual_chrome(
                        start_url=start_url, proxy_server=proxy,
                    )
                    if proxy:
                        log_callback(
                            f"[{pname}] 已启用代理：{proxy.split('@')[-1]}"
                        )
                else:
                    log_callback(f"[{pname}] 检测到已有调试 Chrome，直接连接...")

                cfg = PLATFORM_CONFIG.get(platform_key, {})
                captcha_titles = cfg.get("captcha_title_keywords", [])
                log_callback(f"[{pname}] 等待页面加载...")
                if platform_key == "lagou":
                    if wait_manual_browser_ready(
                        platform_key, captcha_titles, timeout=18.0,
                    ):
                        log_callback(
                            f"[{pname}] Chrome 已打开拉勾首页，"
                            f"程序将自动模拟点击搜索..."
                        )
                    else:
                        log_callback(
                            f"[{pname}] 请在 Chrome 完成首页滑块验证（如有），"
                            f"完成后在弹窗点击「已完成」..."
                        )
                        if not login_confirmation:
                            raise RuntimeError(f"{pname} 需要手动验证，但程序未提供确认回调")
                        if not login_confirmation(pname, 300):
                            raise RuntimeError(f"{pname} 未完成手动验证")
                elif wait_manual_browser_ready(
                    platform_key, captcha_titles, timeout=18.0,
                ):
                    log_callback(f"[{pname}] 页面已就绪，自动继续查询...")
                elif platform_key == "liepin":
                    log_callback(
                        f"[{pname}] 请在 Chrome 打开 www.liepin.com，"
                        f"查询开始后请在浏览器手动搜索关键词（无需登录）..."
                    )
                    wait_manual_browser_ready(
                        platform_key, captcha_titles, timeout=30.0,
                    )
                else:
                    log_callback(
                        f"[{pname}] 未检测到正常页面（可能仍在验证中），"
                        f"请在 Chrome 完成验证后，在弹窗点击「已完成」..."
                    )
                    if not login_confirmation:
                        raise RuntimeError(f"{pname} 需要手动验证，但程序未提供确认回调")
                    if not login_confirmation(pname, 300):
                        raise RuntimeError(f"{pname} 未完成手动验证")

                log_callback(f"[{pname}] 正在连接浏览器...")
                attach_domain = "lagou.com" if platform_key == "lagou" else ""
                self._driver = attach_to_chrome(
                    platform_domain=attach_domain,
                    log=log_callback,
                )
                if platform_key == "liepin":
                    ensure_liepin_home_tab(self._driver, log=log_callback)
                    install_liepin_capture_hook(self._driver)
                self._driver_mode = "attach"
                log_callback(f"[{pname}] 已连接浏览器，开始查询...")
            elif self._attached_platform != platform_key:
                log_callback(f"[{pname}] 复用已连接的 Chrome，切换平台页面...")
                if platform_key == "liepin":
                    ensure_liepin_home_tab(self._driver, log=log_callback)
                    install_liepin_capture_hook(self._driver)
            self._attached_platform = platform_key
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
        city_name: str = "",
        stop_check: Callable[[], bool] = lambda: False,
        log_callback: Callable[[str], None] = print,
        stop_event: Optional[Event] = None,
        page_callback: Optional[Callable[[str, int, List[CompanyInfo], int], None]] = None,
        credentials: Optional[Credentials] = None,
        login_confirmation: Optional[Callable[[str, int], bool]] = None,
    ) -> CrawlResult:
        if platform_key not in PLATFORM_CONFIG:
            return CrawlResult([], CRAWL_BLOCKED, f"未知平台: {platform_key}")

        if platform_key == "lagou":
            return self._crawl_lagou(
                keyword, city_name, count, stop_check, log_callback,
                stop_event, page_callback, login_confirmation,
            )

        if platform_key == "liepin":
            return self._crawl_liepin(
                keyword, city_name, city_code, count, stop_check, log_callback,
                stop_event, page_callback, login_confirmation, credentials,
            )

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
                if not auth.ensure_boss_login(
                    resolve_credentials(platform_key, credentials),
                    login_confirmation,
                ):
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
            if results:
                return CrawlResult(
                    results, CRAWL_OK,
                    f"部分成功：已获取 {len(results)} 条（查询异常：{exc}）",
                )
            return CrawlResult([], CRAWL_BLOCKED, f"{pname} 查询异常：{exc}")
        finally:
            if credentials is not None:
                credentials.clear()

    def _crawl_liepin(
        self,
        keyword: str,
        city_name: str,
        city_code: str,
        count: int,
        stop_check: Callable[[], bool],
        log_callback: Callable[[str], None],
        stop_event: Optional[Event],
        page_callback,
        login_confirmation,
        credentials: Optional[Credentials] = None,
    ) -> CrawlResult:
        """猎聘：浏览器会话 + pc-search-job 接口翻页。"""
        event = stop_event or Event()
        cfg = PLATFORM_CONFIG["liepin"]
        pname = PLATFORMS["liepin"]["name"]
        results: List[CompanyInfo] = []
        seen: set = set()

        try:
            driver = self._ensure_driver(
                "liepin", login_confirmation, log_callback, pname,
            )
            install_liepin_capture_hook(driver)
            creds = resolve_credentials("liepin", credentials)
            ensure_liepin_session(
                driver, event, creds, login_confirmation, log_callback,
            )
            if not navigate_to_liepin_search(
                driver, keyword, city_name, city_code, page=1, log=log_callback,
                stop_event=event,
                credentials=creds,
                login_confirmation=login_confirmation,
            ):
                return CrawlResult(
                    [],
                    CRAWL_BLOCKED,
                    f"{pname} 未能获取职位数据。"
                    f"请在 .credentials.json 配置猎聘账号，或在 Chrome 手动搜索。"
                    f"当前：{driver.title}",
                )

            human_pause(2.0, 3.0)
            list_url = build_liepin_list_url(keyword, city_name, city_code=city_code)

            page_limit = MAX_PAGES
            completed_pages = 0

            for page in range(1, page_limit + 1):
                if event.is_set() or stop_check():
                    return CrawlResult(results, CRAWL_OK, f"用户中止，已获取 {len(results)} 条")

                if page > 1:
                    delay = random.uniform(4, 7)
                    log_callback(f"[{pname}] 翻页间隔 {delay:.0f} 秒...")
                    time.sleep(delay)
                    data = fetch_liepin_page_with_retry(
                        driver, keyword, page, city_name, city_code,
                        list_url, log_callback, max_retries=2,
                    )
                else:
                    data = collect_liepin_page_data(
                        driver, keyword, page, city_name, city_code, log_callback,
                    )
                    if not is_liepin_success(data):
                        data = fetch_liepin_page_with_retry(
                            driver, keyword, page, city_name, city_code,
                            list_url, log_callback, max_retries=2,
                        )

                page_data: List[CompanyInfo] = []
                if not is_liepin_success(data):
                    if page == 1:
                        log_callback(f"[{pname}] 接口未返回数据，尝试解析页面 DOM...")
                        page_data = self._liepin_fallback_dom(
                            driver, cfg, seen, log_callback,
                        )
                        if not page_data:
                            return CrawlResult(
                                [], CRAWL_BLOCKED,
                                f"{pname} 获取失败：{format_liepin_error(data)}。"
                                f"页面标题：{driver.title}",
                            )
                    else:
                        log_callback(f"[{pname}] 第 {page} 页接口无数据，停止翻页")
                        break
                else:
                    inner = data.get("data") or {}
                    pagination = inner.get("pagination") or {}
                    cards = (inner.get("data") or {}).get("jobCardList") or []
                    for item in parse_liepin_positions(cards):
                        key = self._dedupe_key(item, cfg)
                        if key in seen:
                            continue
                        seen.add(key)
                        page_data.append(item)
                    total_page = int(pagination.get("totalPage") or 1)
                    page_limit = min(page_limit, total_page)

                if not page_data:
                    log_callback(f"[{pname}] 第 {page} 页无新增数据")
                    break

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
                if page >= page_limit:
                    break

            if results:
                return CrawlResult(
                    results, CRAWL_OK,
                    f"成功获取 {len(results)} 条（共 {completed_pages} 页）",
                )
            return CrawlResult(
                [],
                CRAWL_BLOCKED,
                f"{pname} 未获取到数据。页面标题：{driver.title}",
            )
        except RuntimeError as exc:
            return CrawlResult([], CRAWL_BLOCKED, str(exc))
        except TimeoutException as exc:
            log_callback(f"[{pname}] 浏览器响应超时：{exc}")
            if results:
                return CrawlResult(
                    results, CRAWL_OK,
                    f"部分成功：已获取 {len(results)} 条（浏览器超时）",
                )
            return CrawlResult(
                [], CRAWL_BLOCKED,
                f"{pname} 浏览器响应超时。请关闭多余 Chrome 窗口后重试。",
            )
        except Exception as exc:
            log_callback(f"[{pname}] 查询异常：{exc}")
            if results:
                return CrawlResult(
                    results, CRAWL_OK,
                    f"部分成功：已获取 {len(results)} 条（查询异常：{exc}）",
                )
            return CrawlResult([], CRAWL_BLOCKED, f"{pname} 查询异常：{exc}")

    def _liepin_fallback_dom(
        self,
        driver,
        cfg,
        seen: set,
        log_callback: Callable[[str], None],
    ) -> List[CompanyInfo]:
        """接口失败时回退到页面 DOM 解析。"""
        page_data = []
        for item in extract_jobs_from_dom(driver, log_callback):
            key = self._dedupe_key(item, cfg)
            if key in seen:
                continue
            seen.add(key)
            page_data.append(item)
        if page_data:
            log_callback(f"[猎聘] DOM 回退解析到 {len(page_data)} 条")
        return page_data

    def _crawl_lagou(
        self,
        keyword: str,
        city_name: str,
        count: int,
        stop_check: Callable[[], bool],
        log_callback: Callable[[str], None],
        stop_event: Optional[Event],
        page_callback,
        login_confirmation,
    ) -> CrawlResult:
        """拉勾：浏览器内点击翻页（模拟人工），Ajax 仅作第 1 页兜底。"""
        event = stop_event or Event()
        cfg = PLATFORM_CONFIG["lagou"]
        pname = PLATFORMS["lagou"]["name"]
        results: List[CompanyInfo] = []
        seen = set()

        try:
            reset_pacer()
            driver = self._ensure_driver(
                "lagou", login_confirmation, log_callback, pname,
            )
            list_url = build_wn_search_url(keyword, city_name)

            def _on_lagou_captcha() -> bool:
                return self._resolve_captcha_page(
                    driver, cfg, pname, list_url, login_confirmation,
                    log_callback, stop_check, reload_target=False,
                )

            if not navigate_to_lagou_search(
                driver, keyword, city_name, log_callback,
                detect_captcha_fn=lambda: self._detect_captcha(
                    driver, cfg, log_callback,
                ),
                on_captcha_fn=_on_lagou_captcha,
                login_confirmation=login_confirmation,
                stop_check=stop_check,
            ):
                return CrawlResult(
                    [], CRAWL_BLOCKED,
                    f"{pname} 未能获取搜索结果。"
                    f"请完成滑块验证后重试。当前：{driver.title}",
                )

            list_url = resolve_lagou_referer(driver, keyword, city_name)

            human_pause(2.0, 4.0)

            total_pages = read_lagou_total_pages(driver)
            page_limit = min(MAX_PAGES, total_pages or 30)
            if total_pages:
                log_callback(f"[{pname}] 页面显示共 {total_pages} 页")
            elif not lagou_has_pager(driver):
                log_callback(
                    f"[{pname}] 新版页面无经典分页条，"
                    f"第 1 页后将使用接口翻页（间隔较长）"
                )

            last_signature = None
            completed_pages = 0
            page = read_lagou_current_page(driver) or 1
            stuck_streak = 0
            contact_search_visited: set = set()
            lagou_use_ajax_paging = False

            while page <= page_limit:
                if event.is_set() or stop_check():
                    return CrawlResult(results, CRAWL_OK, f"用户中止，已获取 {len(results)} 家")

                pager_page = read_lagou_current_page(driver)
                if pager_page and pager_page != page:
                    page = pager_page

                if page > 1:
                    delay = random.uniform(10, 16) + min(page - 1, 8) * 2
                    log_callback(f"[{pname}] 翻页间隔 {delay:.0f} 秒...")
                    time.sleep(delay)

                self._scroll_for_lazy_load(driver, event)
                items = find_current_page_lagou_items(driver)
                if not items:
                    items = self._wait_for_items(driver, cfg)
                    items = [el for el in items if el.is_displayed()]

                page_data: List[CompanyInfo] = []
                if items:
                    signature = lagou_position_signature(items)
                    if signature and signature == last_signature:
                        log_callback(f"[{pname}] 第 {page} 页列表与上页相同，尝试翻页...")
                        stuck_streak += 1
                        if stuck_streak >= 2:
                            log_callback(f"[{pname}] 连续 {stuck_streak} 次列表未变化，停止")
                            break
                    else:
                        stuck_streak = 0
                        last_signature = signature
                        page_data = self._parse_lagou_items(items, cfg, seen)
                        self._enrich_lagou_page_data(
                            driver, keyword, city_name, list_url, page,
                            page_data, log_callback,
                        )
                        fill_contacts_from_company_pages(
                            driver, page_data,
                            driver.current_url or list_url,
                            contact_search_visited, log_callback, stop_check,
                        )
                elif not items:
                    log_callback(
                        f"[{pname}] 页面未渲染卡片，接口加载第 {page} 页..."
                    )
                    lagou_simulate_browse(driver, stop_check=stop_check)
                    page_data, ajax_total = self._lagou_fetch_via_ajax(
                        driver, keyword, city_name, list_url, page, seen,
                        log_callback, contact_search_visited, stop_check,
                    )
                    if not page_data and (
                        self._detect_captcha(driver, cfg, log_callback)
                        or is_lagou_waf_page(driver)
                    ):
                        log_callback(
                            f"[{pname}] 接口被 WAF 拦截，请先完成浏览器滑块验证..."
                        )
                        if self._resolve_captcha_page(
                            driver, cfg, pname, list_url, login_confirmation,
                            log_callback, stop_check, reload_target=True,
                        ):
                            list_url = resolve_lagou_referer(
                                driver, keyword, city_name,
                            )
                            page_data, ajax_total = self._lagou_fetch_via_ajax(
                                driver, keyword, city_name, list_url, page, seen,
                                log_callback, contact_search_visited, stop_check,
                            )
                    if ajax_total:
                        page_limit = min(MAX_PAGES, ajax_total)
                        if page == 1:
                            log_callback(f"[{pname}] 接口显示共 {ajax_total} 页")
                    if page_data:
                        lagou_use_ajax_paging = True

                if not page_data:
                    if page == 1:
                        return CrawlResult(
                            [], CRAWL_BLOCKED,
                            f"{pname} 未获取到数据。关键词「{keyword}」在当前城市可能无结果。",
                        )
                    log_callback(
                        f"[{pname}] 第 {page} 页无新增公司（累计 {len(results)} 家）"
                    )
                else:
                    results.extend(page_data)
                    completed_pages = page
                    log_callback(
                        f"[{pname}] 第 {page} 页新增 {len(page_data)} 家，累计 {len(results)} 家"
                    )
                    if page_callback:
                        page_callback(pname, page, page_data, len(results))
                    if count > 0 and len(results) >= count:
                        results = results[:count]
                        break

                if page >= page_limit:
                    break
                if count > 0 and len(results) >= count:
                    break

                if lagou_use_ajax_paging:
                    completed_pages = self._lagou_ajax_paging_loop(
                        driver, keyword, city_name, list_url,
                        page, page_limit, seen, results,
                        contact_search_visited, log_callback, stop_check,
                        event, page_callback, pname, count,
                        completed_pages, cfg, login_confirmation,
                    )
                    break

                next_target = page + 1

                new_page = go_next_lagou_page(
                    driver, page, last_signature or (), log_callback,
                )
                if new_page <= page:
                    cur = read_lagou_current_page(driver) or page
                    landed = go_to_lagou_page(
                        driver, next_target, cur, last_signature or (), log_callback,
                    )
                    if landed > page:
                        new_page = landed
                    else:
                        wn_url = build_wn_search_url(keyword, city_name, next_target)
                        log_callback(
                            f"[{pname}] 点击翻页未到第 {next_target} 页，"
                            f"尝试打开搜索页..."
                        )
                        soft_navigate(driver, wn_url, log_callback)
                        human_pause(3.0, 5.0)
                        synced = (
                            read_lagou_current_page(driver)
                            or sync_lagou_page_from_browser(driver, next_target)
                        )
                        items_after = find_current_page_lagou_items(driver)
                        if synced > page or items_after:
                            new_sig = lagou_position_signature(items_after)
                            if items_after and (
                                not last_signature or new_sig != last_signature
                            ):
                                new_page = synced if synced > page else next_target
                            elif synced > page:
                                new_page = synced

                if new_page <= page:
                    log_callback(
                        f"[{pname}] 浏览器无法翻到第 {next_target} 页，"
                        f"尝试接口（间隔较长）..."
                    )
                    ap_data, ajax_total = self._lagou_fetch_via_ajax(
                        driver, keyword, city_name, list_url, next_target, seen,
                        log_callback, contact_search_visited, stop_check,
                        max_retries=5,
                    )
                    if ajax_total:
                        page_limit = min(MAX_PAGES, ajax_total)
                    if ap_data:
                        results.extend(ap_data)
                        completed_pages = next_target
                        log_callback(
                            f"[{pname}] 第 {next_target} 页新增 {len(ap_data)} 家，"
                            f"累计 {len(results)} 家"
                        )
                        if page_callback:
                            page_callback(pname, next_target, ap_data, len(results))
                        if count > 0 and len(results) >= count:
                            results = results[:count]
                            break
                        completed_pages = self._lagou_ajax_paging_loop(
                            driver, keyword, city_name, list_url,
                            next_target, page_limit, seen, results,
                            contact_search_visited, log_callback, stop_check,
                            event, page_callback, pname, count,
                            completed_pages, cfg, login_confirmation,
                        )
                        break
                    ap_data = self._parse_open_lagou_page(
                        driver, next_target, cfg, seen,
                        contact_search_visited, log_callback, stop_check,
                    )
                    if ap_data:
                        results.extend(ap_data)
                        completed_pages = next_target
                        page = next_target
                        human_pause(2.0, 3.5)
                        continue
                    log_callback(f"[{pname}] 翻页结束（停在第 {page} 页）")
                    break

                if self._detect_captcha(driver, cfg, log_callback):
                    log_callback(f"[{pname}] 翻页后触发验证，请完成验证后继续...")
                    if not self._resolve_captcha_page(
                        driver, cfg, pname, list_url, login_confirmation,
                        log_callback, stop_check, reload_target=False,
                    ):
                        log_callback(f"[{pname}] 验证未通过，保留已采集数据")
                        break

                page = new_page
                human_pause(2.0, 3.5)

            if results:
                return CrawlResult(
                    results, CRAWL_OK,
                    f"成功获取 {len(results)} 家公司（浏览 {completed_pages} 页）",
                )
            return CrawlResult(
                [],
                CRAWL_BLOCKED,
                f"{pname} 未获取到数据。当前：{driver.title}",
            )
        except RuntimeError as exc:
            return CrawlResult([], CRAWL_BLOCKED, str(exc))
        except TimeoutException as exc:
            log_callback(f"[{pname}] 浏览器响应超时：{exc}")
            if results:
                return CrawlResult(
                    results, CRAWL_OK,
                    f"部分成功：已获取 {len(results)} 条（浏览器超时）",
                )
            return CrawlResult(
                [], CRAWL_BLOCKED,
                f"{pname} 浏览器响应超时。请关闭多余 Chrome 窗口后重试。",
            )
        except Exception as exc:
            log_callback(f"[{pname}] 查询异常：{exc}")
            if results:
                return CrawlResult(
                    results, CRAWL_OK,
                    f"部分成功：已获取 {len(results)} 家（查询异常：{exc}）",
                )
            return CrawlResult([], CRAWL_BLOCKED, f"{pname} 查询异常：{exc}")

    def _wait_for_lagou_user_search(
        self,
        driver,
        keyword: str,
        city_name: str,
        cfg,
        pname: str,
        list_url: str,
        login_confirmation,
        log_callback: Callable[[str], None],
        stop_check: Callable[[], bool],
        timeout: float = 300,
    ) -> bool:
        """等待用户在 Chrome 手动搜索，避免自动跳转触发拉勾验证。"""
        if is_lagou_search_url(driver.current_url or "", keyword):
            if find_current_page_lagou_items(driver):
                log_callback(f"[{pname}] 已在搜索结果页")
                return True

        log_callback(f"[{pname}] 请在 Chrome 中手动搜索（程序不会自动输入或提交）：")
        log_callback(f"[{pname}]   1. 在拉勾首页搜索框输入「{keyword}」")
        if city_name and city_name != "全国":
            log_callback(f"[{pname}]   2. 城市选择「{city_name}」后回车搜索")
        else:
            log_callback(f"[{pname}]   2. 回车搜索")
        log_callback(f"[{pname}]   3. 如出现滑块，请在浏览器中完成验证")
        log_callback(f"[{pname}] 等待搜索结果（最多 {int(timeout)} 秒）...")

        deadline = time.monotonic() + timeout
        last_status = 0.0
        while time.monotonic() < deadline:
            if stop_check():
                return False

            if find_current_page_lagou_items(driver):
                log_callback(f"[{pname}] 已检测到职位列表，开始采集")
                return True

            if self._detect_captcha(driver, cfg, log_callback):
                log_callback(
                    f"[{pname}] 检测到验证页，请在浏览器完成滑块；"
                    "失败时请手动刷新页面后重试"
                )
                if login_confirmation and login_confirmation(pname, 180):
                    human_pause(2.0, 3.0)
                    continue
                return False

            now = time.monotonic()
            if now - last_status >= 15:
                try:
                    cur_url = (driver.current_url or "")[:80]
                except WebDriverException:
                    cur_url = "(未知)"
                log_callback(f"[{pname}] 等待手动搜索… 当前页: {cur_url}")
                last_status = now

            time.sleep(2)

        return False

    def _parse_lagou_items(self, items, cfg, seen) -> List[CompanyInfo]:
        """解析拉勾列表页。"""
        page_data: List[CompanyInfo] = []
        for item in items:
            try:
                info = cfg["parse_fn"](item)
                if not info:
                    continue
                key = self._dedupe_key(info, cfg)
                if key in seen:
                    continue
                seen.add(key)
                page_data.append(info)
            except Exception:
                continue
        return page_data

    def _lagou_cooldown_ajax_retry(
        self,
        driver,
        keyword: str,
        city_name: str,
        list_url: str,
        page: int,
        seen: set,
        log_callback: Callable[[str], None],
        contact_search_visited: set,
        stop_check: Callable[[], bool],
        pname: str,
        cfg,
        login_confirmation,
    ) -> tuple[List[CompanyInfo], int]:
        """限流后长暂停，回到第 1 页搜索再试一次 Ajax（Referer 仍指向目标页）。"""
        wait = lagou_backoff_wait(3) + random.uniform(60.0, 90.0)
        log_callback(
            f"[{pname}] 第 {page} 页限流持续，退避 {wait:.0f} 秒后回到第 1 页再试..."
        )
        time.sleep(wait)
        base_url = build_wn_search_url(keyword, city_name, 1)
        soft_navigate(driver, base_url, log_callback)
        human_pause(4.0, 7.0)
        lagou_simulate_browse(driver, stop_check=stop_check)
        if (
            self._detect_captcha(driver, cfg, log_callback)
            or is_lagou_waf_page(driver)
        ):
            log_callback(f"[{pname}] 请在浏览器中完成滑块验证...")
            if not self._resolve_captcha_page(
                driver, cfg, pname, base_url, login_confirmation,
                log_callback, stop_check, reload_target=True,
            ):
                return [], 0
        referer = lagou_referer_for_page(keyword, city_name, page)
        return self._lagou_fetch_via_ajax(
            driver, keyword, city_name, referer, page, seen,
            log_callback, contact_search_visited, stop_check,
            max_retries=1,
            skip_pre_pause=True,
        )

    def _lagou_try_resolve_waf(
        self,
        driver,
        cfg,
        pname: str,
        keyword: str,
        city_name: str,
        login_confirmation,
        log_callback: Callable[[str], None],
        stop_check: Callable[[], bool],
    ) -> bool:
        if not (
            self._detect_captcha(driver, cfg, log_callback)
            or is_lagou_waf_page(driver)
        ):
            return True
        base_url = build_wn_search_url(keyword, city_name, 1)
        log_callback(f"[{pname}] 检测到滑块/验证页，请在浏览器中完成验证...")
        return self._resolve_captcha_page(
            driver, cfg, pname, base_url, login_confirmation,
            log_callback, stop_check, reload_target=True,
        )

    def _lagou_ajax_paging_loop(
        self,
        driver,
        keyword: str,
        city_name: str,
        list_url: str,
        current_page: int,
        page_limit: int,
        seen: set,
        results: List[CompanyInfo],
        contact_search_visited: set,
        log_callback: Callable[[str], None],
        stop_check: Callable[[], bool],
        event: Event,
        page_callback,
        pname: str,
        count: int,
        completed_pages: int,
        cfg,
        login_confirmation,
    ) -> int:
        """仅用 Ajax 顺序拉取 current_page 之后的页，每页只请求一次。"""
        page = current_page
        limit = page_limit

        while page < limit:
            if event.is_set() or stop_check():
                break
            if count > 0 and len(results) >= count:
                break

            next_p = page + 1
            log_callback(f"[{pname}] 准备接口翻页第 {next_p} 页...")
            referer = lagou_prepare_ajax_page(
                driver, keyword, city_name, next_p, log_callback,
                stop_check=stop_check,
            )
            if not self._lagou_try_resolve_waf(
                driver, cfg, pname, keyword, city_name,
                login_confirmation, log_callback, stop_check,
            ):
                log_callback(f"[{pname}] 验证未通过，停止翻页（累计 {len(results)} 家）")
                break

            ap_data, ajax_total = self._lagou_fetch_via_ajax(
                driver, keyword, city_name, referer, next_p, seen,
                log_callback, contact_search_visited, stop_check,
                max_retries=LAGOU_AJAX_MAX_RETRIES,
                skip_pre_pause=True,
            )
            if ajax_total:
                limit = min(MAX_PAGES, ajax_total)

            if not ap_data and (
                self._detect_captcha(driver, cfg, log_callback)
                or is_lagou_waf_page(driver)
            ):
                if self._lagou_try_resolve_waf(
                    driver, cfg, pname, keyword, city_name,
                    login_confirmation, log_callback, stop_check,
                ):
                    referer = lagou_referer_for_page(keyword, city_name, next_p)
                    ap_data, ajax_total = self._lagou_fetch_via_ajax(
                        driver, keyword, city_name, referer, next_p, seen,
                        log_callback, contact_search_visited, stop_check,
                        max_retries=1,
                        skip_pre_pause=True,
                    )
                    if ajax_total:
                        limit = min(MAX_PAGES, ajax_total)

            if not ap_data:
                ap_data, ajax_total = self._lagou_cooldown_ajax_retry(
                    driver, keyword, city_name, list_url, next_p, seen,
                    log_callback, contact_search_visited, stop_check, pname,
                    cfg, login_confirmation,
                )
                if ajax_total:
                    limit = min(MAX_PAGES, ajax_total)

            if not ap_data:
                log_callback(
                    f"[{pname}] 接口第 {next_p} 页无数据，停止翻页"
                    f"（累计 {len(results)} 家）。"
                    f"若持续限流，请删除 .manual_browser 目录后重新过滑块，"
                    f"或稍后再试。"
                )
                break

            results.extend(ap_data)
            completed_pages = next_p
            log_callback(
                f"[{pname}] 第 {next_p} 页新增 {len(ap_data)} 家，"
                f"累计 {len(results)} 家"
            )
            if page_callback:
                page_callback(pname, next_p, ap_data, len(results))
            if count > 0 and len(results) >= count:
                results[:] = results[:count]
                break
            page = next_p
            list_url = lagou_referer_for_page(keyword, city_name, next_p)
            human_pause(2.0, 4.0)

        return completed_pages

    def _parse_open_lagou_page(
        self,
        driver,
        expected_page: int,
        cfg,
        seen: set,
        contact_search_visited: set,
        log_callback: Callable[[str], None],
        stop_check: Callable[[], bool],
    ) -> List[CompanyInfo]:
        """接口受限时，仅解析浏览器中已实际打开的目标页，不主动跳转。"""
        browser_page = read_lagou_current_page(driver)
        if not browser_page:
            try:
                params = urllib.parse.parse_qs(
                    urllib.parse.urlparse(driver.current_url or "").query,
                )
                browser_page = int((params.get("pn") or ["1"])[0])
            except (TypeError, ValueError, WebDriverException):
                browser_page = 1
        if browser_page != expected_page:
            log_callback(
                f"[拉勾网] 接口受限；浏览器当前为第 {browser_page} 页，"
                f"不是目标第 {expected_page} 页"
            )
            return []

        items = find_current_page_lagou_items(driver)
        if not items:
            return []

        page_data = self._parse_lagou_items(items, cfg, seen)
        if not page_data:
            return []

        log_callback(f"[拉勾网] 接口受限，改为解析浏览器已打开的第 {expected_page} 页")
        fill_contacts_from_company_pages(
            driver, page_data, driver.current_url or "",
            contact_search_visited, log_callback, stop_check,
        )
        return page_data

    def _enrich_lagou_page_data(
        self,
        driver,
        keyword: str,
        city_name: str,
        list_url: str,
        page: int,
        page_data: List[CompanyInfo],
        log_callback: Callable[[str], None],
    ) -> Optional[dict]:
        """DOM 缺字段时，用同页 Ajax 数据补全行业/规模，返回 lookup。"""
        if not page_data:
            return None
        needs = [
            c for c in page_data
            if c.industry in ("—", "") or c.scale in ("—", "")
        ]
        try:
            data = fetch_lagou_page_with_retry(
                driver, keyword, page, city_name, list_url, log_callback,
                max_retries=1,
            )
        except Exception as exc:
            log_callback(f"[拉勾网] 补全第 {page} 页字段失败：{exc}")
            return None
        if not data or not data.get("success"):
            return None
        positions = (
            data.get("content", {})
            .get("positionResult", {})
            .get("result", [])
        )
        lookup = build_lagou_company_lookup(positions)
        enrich_lagou_companies(page_data, lookup)
        if needs:
            log_callback(f"[拉勾网] 第 {page} 页接口补全 {len(needs)} 家字段")
        return lookup

    def _lagou_fetch_via_ajax(
        self,
        driver,
        keyword: str,
        city_name: str,
        list_url: str,
        page: int,
        seen: set,
        log_callback: Callable[[str], None],
        contact_search_visited: set,
        stop_check: Callable[[], bool],
        max_retries: int = 5,
        skip_pre_pause: bool = False,
    ) -> tuple[List[CompanyInfo], int]:
        try:
            data = fetch_lagou_page_with_retry(
                driver, keyword, page, city_name, list_url, log_callback,
                max_retries=max_retries,
                skip_pre_pause=skip_pre_pause,
            )
        except Exception as exc:
            log_callback(f"[拉勾网] Ajax 异常：{exc}")
            return [], 0
        if not data or not data.get("success"):
            log_callback(f"[拉勾网] Ajax 失败：{format_lagou_error(data)}")
            return [], 0
        positions, total_pages, _ = extract_lagou_ajax_result(data)
        page_data = []
        for item in parse_lagou_positions(positions):
            key = (item.name,)
            if key in seen:
                continue
            seen.add(key)
            item.hot_jobs = ""
            item.salary = ""
            page_data.append(item)
        if not page_data:
            return [], total_pages
        lookup = build_lagou_company_lookup(positions)
        enrich_lagou_companies(page_data, lookup)
        fill_contacts_from_company_pages(
            driver, page_data,
            driver.current_url or list_url,
            contact_search_visited, log_callback, stop_check,
        )
        return page_data, total_pages

    @staticmethod
    def _has_visible_results(driver, cfg) -> bool:
        item_css = cfg.get("item_css", "")
        if not item_css:
            return False
        try:
            for item in driver.find_elements(By.CSS_SELECTOR, item_css):
                if item.is_displayed():
                    size = item.size or {}
                    if size.get("height", 0) > 0:
                        return True
        except WebDriverException:
            pass
        return False

    @staticmethod
    def _try_refresh_on_verify_failure(driver, cfg, log_callback=None, enabled: bool = True) -> bool:
        if not enabled:
            return False
        fail_keywords = cfg.get("captcha_fail_keywords", [])
        if not fail_keywords:
            return False
        try:
            body = (driver.find_element(By.TAG_NAME, "body").text or "").strip()
        except WebDriverException:
            return False
        if not any(kw in body for kw in fail_keywords):
            return False
        if log_callback:
            log_callback("[验证] 检测到「验证失败」，正在自动刷新页面...")
        try:
            driver.refresh()
        except WebDriverException:
            safe_get(driver, driver.current_url or "", log_callback)
        human_pause(2.5, 4.0)
        return True

    @staticmethod
    def _detect_captcha(driver, cfg, log_callback=None) -> bool:
        """检测是否处于验证/安全拦截页（避免误匹配正文里的普通文案）。"""
        time.sleep(0.4)

        # 职位列表已可见时，即使标题仍显示「访问验证」也视为通过。
        if CrawlerEngine._has_visible_results(driver, cfg):
            return False

        title = driver.title or ""

        for kw in cfg.get("captcha_title_keywords", []):
            if kw in title:
                if log_callback:
                    log_callback(f"[验证检测] 标题匹配 '{kw}'")
                return True

        captcha_css = cfg.get("captcha_css", "")
        if captcha_css:
            try:
                for element in driver.find_elements(By.CSS_SELECTOR, captcha_css):
                    if element.is_displayed():
                        if log_callback:
                            log_callback("[验证检测] 发现验证组件")
                        return True
            except WebDriverException:
                pass

        body_keywords = cfg.get("captcha_body_keywords", [])
        if not body_keywords:
            return False

        verify_regions = (
            "[class*='verify']",
            "[class*='captcha']",
            "[class*='access-verify']",
            ".geetest_panel",
            "#tcaptcha",
        )
        try:
            for region_sel in verify_regions:
                for el in driver.find_elements(By.CSS_SELECTOR, region_sel):
                    if not el.is_displayed():
                        continue
                    text = (el.text or "").strip()
                    if not text:
                        continue
                    for kw in body_keywords:
                        if kw in text:
                            if log_callback:
                                log_callback(f"[验证检测] 验证区匹配 '{kw}'")
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
        reload_target: bool = True,
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

            self._try_refresh_on_verify_failure(
                driver, cfg, log_callback, enabled=reload_target,
            )

            if not self._detect_captcha(driver, cfg, log_callback):
                log_callback(f"[{pname}] 验证已通过，继续查询...")
                return True

            if round_i == 0:
                log_callback(
                    f"[{pname}] 检测到验证页，请在浏览器中完成滑块/验证；"
                    f"若提示失败请先点刷新再重试"
                )
            else:
                log_callback(
                    f"[{pname}] 验证仍未通过（第 {round_i + 1}/{max_rounds} 次）。"
                    "请在浏览器中手动刷新页面后再重试。"
                )

            if not login_confirmation(pname, wait_sec):
                return False

            human_pause(1.5, 2.5)
            if reload_target and target_url:
                log_callback(f"[{pname}] 正在重新加载搜索页...")
                safe_get(driver, target_url, log_callback)
                human_pause(2.0, 3.5)
                self._try_refresh_on_verify_failure(driver, cfg, log_callback)

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
    def _dedupe_key(info: CompanyInfo, cfg) -> tuple:
        if cfg.get("dedupe_by") == "name":
            return (info.name,)
        return (info.name, info.hot_jobs, info.location)

    @staticmethod
    def _parse_page(items, cfg, seen) -> List[CompanyInfo]:
        page_data = []
        for item in items:
            try:
                info = cfg["parse_fn"](item)
                if not info:
                    continue
                key = CrawlerEngine._dedupe_key(info, cfg)
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

    def _go_next_page(
        self, driver, cfg, page, keyword, city_code, event: Event,
        list_url: str = "",
    ) -> bool:
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

        if list_url:
            return False

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
