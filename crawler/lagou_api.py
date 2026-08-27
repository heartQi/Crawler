#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉勾网 Ajax 接口 — 职位列表由 positionAjax.json 动态加载。"""

from __future__ import annotations

import random
import re
import time
import urllib.parse
from typing import Callable, List, Optional

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from .browser import safe_get, soft_navigate
from .config import (
    CRAWL_BACKOFF_MAX,
    CRAWL_REQUEST_DELAY,
    LAGOU_AJAX_HIGH_PAGE_EXTRA,
    LAGOU_AJAX_INTERVAL,
    LAGOU_AJAX_LONG_PAUSE,
    LAGOU_AJAX_LONG_PAUSE_EVERY,
    LAGOU_AJAX_MAX_RETRIES,
    LAGOU_AJAX_PAGE_EXTRA,
    LAGOU_BACKOFF_BASE,
    LAGOU_BACKOFF_FACTOR,
    LAGOU_BACKOFF_JITTER,
    USER_AGENTS,
)
from .models import CompanyInfo
from .pacing import get_pacer
from .stealth import gentle_scroll, human_pause

PHONE_RE = re.compile(
    r"1[3-9]\d{9}|0\d{2,3}[-\s]?\d{7,8}|(?:\d{3,4}[-\s]){1,2}\d{3,8}",
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_lagou_contact(position: dict) -> tuple[str, str]:
    """从拉勾职位 JSON 提取联系人、联系方式。"""
    person = ""
    info = ""

    for key in ("publisherName", "hrName", "contactName", "recruiterName"):
        val = position.get(key)
        if val:
            person = str(val).strip()
            break

    hr = position.get("hrInfo") or position.get("hr")
    if isinstance(hr, dict):
        person = person or str(hr.get("name") or hr.get("publisherName") or "").strip()
        for key in ("phone", "mobile", "tel", "contactPhone", "email"):
            val = hr.get(key)
            if val:
                info = str(val).strip()
                break

    for key in ("phone", "mobile", "contactPhone", "hrPhone", "tel", "email"):
        val = position.get(key)
        if val:
            info = str(val).strip()
            break

    if not info:
        blob = " ".join(str(position.get(k, "")) for k in ("positionAdvantage", "companyLabelList"))
        phone = PHONE_RE.search(blob)
        if phone:
            info = phone.group(0)
        else:
            email = EMAIL_RE.search(blob)
            if email:
                info = email.group(0)

    return person or "—", info or "—"

LIST_URL = "https://www.lagou.com/jobs/list_{kw}"
WN_SEARCH_URL = "https://www.lagou.com/wn/search/"
AJAX_URL = "https://www.lagou.com/jobs/positionAjax.json?needAddtionalResult=false"
MANUAL_SEARCH_TIMEOUT = 300
_last_lagou_ajax_at = 0.0
_lagou_ajax_fetch_count = 0


def lagou_ajax_interval_for_page(page: int) -> float:
    """翻页等待：宽随机区间 + 随页数略增，避免固定节奏。"""
    base = random.uniform(*LAGOU_AJAX_INTERVAL)
    extra = random.uniform(*LAGOU_AJAX_PAGE_EXTRA) * min(max(page - 1, 0), 10)
    jitter = random.uniform(2.0, 12.0) if random.random() < 0.35 else 0.0
    return base + extra + jitter


def lagou_backoff_wait(attempt: int) -> float:
    """限流后等待时长（秒）— 使用拉勾专用退避，不用通用短间隔。"""
    wait = min(
        LAGOU_BACKOFF_BASE * (LAGOU_BACKOFF_FACTOR ** attempt),
        CRAWL_BACKOFF_MAX,
    )
    return wait + random.uniform(*LAGOU_BACKOFF_JITTER)


def lagou_browse_page_before_ajax(
    driver,
    keyword: str,
    city_name: str,
    page: int,
    log: Callable[[str], None] = print,
    stop_check=None,
) -> str:
    """先打开目标页搜索 URL 并模拟浏览，再发 Ajax（降低裸接口特征）。"""
    url = build_wn_search_url(keyword, city_name, page)
    log(f"[拉勾网] 先在浏览器打开第 {page} 页搜索 URL...")
    _sync_lagou_city_cookie(driver, city_name)
    soft_navigate(driver, url, log)
    human_pause(4.0, 7.0)
    lagou_simulate_browse(driver, stop_check=stop_check)
    if page >= 4:
        extra = random.uniform(*LAGOU_AJAX_HIGH_PAGE_EXTRA)
        log(f"[拉勾网] 第 {page} 页额外停留 {extra:.0f} 秒后再请求接口...")
        time.sleep(extra)
    global _last_lagou_ajax_at
    _last_lagou_ajax_at = 0.0
    return resolve_lagou_referer(driver, keyword, city_name)


def lagou_browse_warmup(
    driver,
    log: Callable[[str], None] = print,
    stop_check=None,
) -> None:
    """模拟真实浏览链路：首页停留 → 滚动 → 随机停顿（建立 Cookie/会话）。"""
    try:
        url = driver.current_url or ""
        title = driver.title or ""
    except WebDriverException:
        url, title = "", ""
    if "lagou.com" not in url.lower() or is_lagou_blocked_url(url, title):
        log("[拉勾网] 先访问首页建立会话...")
        soft_navigate(driver, "https://www.lagou.com/wn/", log)
    get_pacer().wait_before_request(
        delay_range=CRAWL_REQUEST_DELAY,
        log=log,
        label="浏览首页",
    )
    lagou_simulate_browse(driver, stop_check=stop_check)
    if random.random() < 0.35:
        human_pause(2.0, 5.0)
        log("[拉勾网] 模拟浏览停顿...")


def lagou_ajax_pause(min_interval: Optional[float] = None) -> None:
    """两次 Ajax 之间强制留白；未达下限则补随机等待。"""
    global _last_lagou_ajax_at
    floor = min_interval or random.uniform(*LAGOU_AJAX_INTERVAL)
    elapsed = time.monotonic() - _last_lagou_ajax_at
    if elapsed < floor:
        time.sleep(floor - elapsed + random.uniform(2.0, 9.0))
    _last_lagou_ajax_at = time.monotonic()


def lagou_simulate_browse(driver, stop_check=None) -> None:
    """翻页前轻量模拟浏览：滚动 + 随机停顿。"""
    try:
        gentle_scroll(driver, stop_check=stop_check)
    except WebDriverException:
        pass
    human_pause(1.2, 3.5)
    if random.random() < 0.4:
        try:
            driver.execute_script(
                "window.scrollTo({top: 0, behavior: 'smooth'});",
            )
            human_pause(0.6, 1.4)
        except WebDriverException:
            pass


def lagou_wait_before_ajax(
    driver,
    page: int,
    log: Callable[[str], None] = print,
    stop_check=None,
) -> None:
    """翻页前等待：随机间隔，周期性长休息，并模拟浏览。"""
    global _lagou_ajax_fetch_count
    _lagou_ajax_fetch_count += 1
    pacer = get_pacer()
    pacer.record_request()
    pacer.maybe_periodic_cooldown(log=log)

    delay = lagou_ajax_interval_for_page(page)
    if (
        LAGOU_AJAX_LONG_PAUSE_EVERY > 0
        and _lagou_ajax_fetch_count > 1
        and _lagou_ajax_fetch_count % LAGOU_AJAX_LONG_PAUSE_EVERY == 0
    ):
        long_pause = random.uniform(*LAGOU_AJAX_LONG_PAUSE)
        log(f"[拉勾网] 已连续请求 {_lagou_ajax_fetch_count} 次，长休息 {long_pause:.0f} 秒...")
        time.sleep(long_pause)
        delay = random.uniform(15.0, 28.0)

    log(f"[拉勾网] 随机等待 {delay:.0f} 秒后再请求第 {page} 页...")
    time.sleep(delay)


def lagou_prepare_ajax_page(
    driver,
    keyword: str,
    city_name: str,
    page: int,
    log: Callable[[str], None] = print,
    stop_check=None,
) -> str:
    """翻页前：计数/冷却 → 浏览器打开目标页 → 返回 referer。"""
    global _lagou_ajax_fetch_count
    _lagou_ajax_fetch_count += 1
    pacer = get_pacer()
    pacer.record_request()
    pacer.maybe_periodic_cooldown(log=log)

    if (
        LAGOU_AJAX_LONG_PAUSE_EVERY > 0
        and _lagou_ajax_fetch_count > 1
        and _lagou_ajax_fetch_count % LAGOU_AJAX_LONG_PAUSE_EVERY == 0
    ):
        long_pause = random.uniform(*LAGOU_AJAX_LONG_PAUSE)
        log(f"[拉勾网] 已连续请求 {_lagou_ajax_fetch_count} 次，长休息 {long_pause:.0f} 秒...")
        time.sleep(long_pause)

    delay = lagou_ajax_interval_for_page(page)
    log(f"[拉勾网] 随机等待 {delay:.0f} 秒...")
    time.sleep(delay)

    return lagou_browse_page_before_ajax(
        driver, keyword, city_name, page, log, stop_check=stop_check,
    )


def _random_lagou_fetch_headers(referer: str) -> dict:
    ua = random.choice(USER_AGENTS)
    lang = random.choice((
        "zh-CN,zh;q=0.9",
        "zh-CN,zh;q=0.9,en;q=0.8",
        "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
    ))
    accept = random.choice((
        "application/json, text/javascript, */*; q=0.01",
        "application/json, text/plain, */*",
    ))
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": accept,
        "Accept-Language": lang,
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Origin": "https://www.lagou.com",
        "User-Agent": ua,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    if random.random() < 0.5:
        headers["Cache-Control"] = random.choice(("no-cache", "max-age=0"))
    return headers


def build_list_url(keyword: str, city: str = "", page: int = 1) -> str:
    """拉勾旧版搜索页 URL（Ajax Referer）。"""
    kw_seg = urllib.parse.quote(keyword)
    url = f"{LIST_URL.format(kw=kw_seg)}?fromSearch=true"
    if city and city != "全国":
        url += f"&city={urllib.parse.quote(city)}"
    if page > 1:
        url += f"&pn={page}"
    return url


def build_wn_search_url(keyword: str, city: str = "", page: int = 1) -> str:
    """拉勾新版 wn/search 搜索页 URL。"""
    parts = [f"kd={urllib.parse.quote(keyword)}"]
    if city and city != "全国":
        parts.append(f"city={urllib.parse.quote(city)}")
    if page > 1:
        parts.append(f"pn={page}")
    return f"{WN_SEARCH_URL}?{'&'.join(parts)}"


def is_lagou_blocked_url(url: str = "", title: str = "") -> bool:
    u = (url or "").lower()
    t = title or ""
    if "passport.lagou" in u or "/login" in u:
        return True
    if any(kw in t for kw in (
        "访问验证", "安全验证", "人机验证", "验证中心",
        "滑动验证", "滑动验证页面", "验证码",
    )):
        return True
    return False


def is_lagou_waf_html(text: str = "") -> bool:
    if not text:
        return False
    low = text.lower()
    return (
        "aliyun_waf" in low
        or "waf_aa" in low
        or "<!doctype" in low
        or "<!DOCTYPE" in text
        or "<html" in low
    )


def is_lagou_waf_page(driver) -> bool:
    try:
        url = driver.current_url or ""
        title = driver.title or ""
    except WebDriverException:
        return False
    if is_lagou_blocked_url(url, title):
        return True
    try:
        snippet = (driver.page_source or "")[:4000].lower()
    except WebDriverException:
        return False
    return "aliyun_waf" in snippet or "滑动验证" in snippet


def is_lagou_search_url(url: str, keyword: str = "", title: str = "") -> bool:
    if not url or "lagou.com" not in url.lower():
        return False
    if is_lagou_blocked_url(url, title):
        return False
    u = url.lower()
    if (
        "/wn/search" in u or "/jobs/list" in u
        or "/wn/zhaopin" in u or "kd=" in u or "key=" in u
    ):
        if not keyword:
            return True
        decoded = urllib.parse.unquote(url)
        return (
            keyword in decoded
            or urllib.parse.quote(keyword) in url
            or keyword.replace(" ", "") in decoded.replace(" ", "")
        )
    return False


LAGOU_SEARCH_INPUT_SELECTORS = (
    "input#search_input",
    "input.search_input",
    "input[name='kd']",
    "input[placeholder*='搜索你想']",
    "input[placeholder*='搜索职位']",
    "input[placeholder*='搜索']",
    "input[placeholder*='职位']",
    "input[placeholder*='关键词']",
    "input[placeholder*='找']",
    ".search-box input",
    ".search_input",
    ".top-search input",
    "[class*='search'] input[type='text']",
    "[class*='Search'] input[type='text']",
    "[class*='search'] input:not([type='hidden'])",
    ".lg-search input",
    "header input[type='text']",
    "input[type='search']",
)
LAGOU_SEARCH_BTN_SELECTORS = (
    "input.search_button",
    "button.search-btn",
    ".search_button",
    ".search-btn",
    "[class*='search-btn']",
    "[class*='Search'] button",
    "[class*='search'] button[type='button']",
    "button[type='submit']",
    "[class*='search-icon']",
    "[class*='searchIcon']",
)
LAGOU_CITY_TRIGGER_SELECTORS = (
    ".city_label",
    "#city_name",
    ".changeCity_text",
    "[class*='city-wrapper']",
    "[class*='change-city']",
    "[class*='changeCity']",
    "[class*='city-name']",
    "[class*='CityName']",
    "[class*='current-city']",
    "[class*='location-city']",
    ".position-header .city",
    "header [class*='city']",
)


def _prepare_lagou_page(driver, log: Callable[[str], None]) -> None:
    try:
        driver.execute_script("window.scrollTo(0, 0);")
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"),
        )
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script(
                "return document.querySelectorAll('input,textarea').length > 0;"
            ),
        )
    except TimeoutException:
        log("[拉勾网] 页面加载较慢，继续尝试搜索...")
    time.sleep(random.uniform(1.2, 2.0))


def _human_click(driver, element) -> None:
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", element,
        )
        ActionChains(driver).move_to_element(element).pause(
            random.uniform(0.15, 0.45),
        ).click(element).perform()
    except WebDriverException:
        driver.execute_script("arguments[0].click();", element)


def _human_type(element, text: str) -> None:
    try:
        element.clear()
    except WebDriverException:
        pass
    for ch in text:
        element.send_keys(ch)
        time.sleep(random.uniform(0.05, 0.14))


def _find_visible_element(driver, selectors) -> Optional[object]:
    for sel in selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if not el.is_displayed() or not el.is_enabled():
                    continue
                size = el.size or {}
                if size.get("width", 0) <= 0 or size.get("height", 0) <= 0:
                    continue
                return el
        except WebDriverException:
            continue
    return None


def _read_city_from_lagou_url(url: str = "") -> str:
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url or "").query)
        raw = (qs.get("city") or [""])[0]
        return urllib.parse.unquote(raw).strip()
    except (TypeError, ValueError):
        return ""


def _lagou_url_matches_city(url: str, city_name: str) -> bool:
    if not city_name or city_name == "全国":
        return True
    if not url:
        return False
    decoded = urllib.parse.unquote(url)
    return city_name in decoded or urllib.parse.quote(city_name) in url


def _sync_lagou_city_cookie(driver, city_name: str) -> None:
    """同步拉勾会话城市 Cookie，使页头显示与配置一致。"""
    if not city_name or city_name == "全国":
        return
    try:
        driver.execute_script(
            """
            const city = arguments[0];
            document.cookie = 'index_location_city='
                + encodeURIComponent(city)
                + '; domain=.lagou.com; path=/';
            try { localStorage.setItem('city', city); } catch (e) {}
            try { sessionStorage.setItem('city', city); } catch (e) {}
            """,
            city_name,
        )
    except WebDriverException:
        pass


def _select_lagou_city_via_js(driver, city_name: str) -> bool:
    if not city_name or city_name == "全国":
        return True
    script = """
    const city = arguments[0];
    const nodes = Array.from(document.querySelectorAll(
        'a, span, li, dd, div, button, p'
    ));
    for (const el of nodes) {
        const t = (el.textContent || '').trim();
        if (t !== city && !t.startsWith(city)) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 8 || r.height < 8) continue;
        el.click();
        return true;
    }
    return false;
    """
    try:
        return bool(driver.execute_script(script, city_name))
    except WebDriverException:
        return False


def _select_lagou_city(driver, city_name: str, log: Callable[[str], None]) -> bool:
    if not city_name or city_name == "全国":
        return True
    trigger = _find_visible_element(driver, LAGOU_CITY_TRIGGER_SELECTORS)
    if trigger is not None:
        current = (trigger.text or "").strip()
        if city_name in current:
            log(f"[拉勾网] 页面城市已是 {city_name}")
            return True
        _human_click(driver, trigger)
        time.sleep(random.uniform(0.5, 1.0))
    city_option_selectors = (
        f"//dd[normalize-space(text())='{city_name}']",
        f"//li[normalize-space(text())='{city_name}']",
        f"//span[normalize-space(text())='{city_name}']",
        f"//a[normalize-space(text())='{city_name}']",
        f"//dd[contains(text(),'{city_name}')]",
        f"//li[contains(text(),'{city_name}')]",
        f"//span[contains(text(),'{city_name}')]",
        f"//a[contains(text(),'{city_name}')]",
        f"//*[contains(@class,'city') and contains(text(),'{city_name}')]",
    )
    for xpath in city_option_selectors:
        try:
            for el in driver.find_elements(By.XPATH, xpath):
                if not el.is_displayed():
                    continue
                _human_click(driver, el)
                log(f"[拉勾网] 已在页面选择城市 {city_name}")
                time.sleep(random.uniform(0.5, 1.0))
                return True
        except WebDriverException:
            continue
    if _select_lagou_city_via_js(driver, city_name):
        log(f"[拉勾网] 已通过脚本选择城市 {city_name}")
        time.sleep(random.uniform(0.4, 0.8))
        return True
    log(f"[拉勾网] 首页未能切换城市，将通过搜索 URL 指定 {city_name}")
    return False


def _open_lagou_search_page(
    driver,
    keyword: str,
    city_name: str,
    log: Callable[[str], None],
) -> str:
    """打开带城市与关键词的搜索页，并同步 Cookie。"""
    wn_url = build_wn_search_url(keyword, city_name)
    city_label = city_name if city_name and city_name != "全国" else "全国"
    log(f"[拉勾网] 打开搜索页：{city_label} · {keyword}")
    _sync_lagou_city_cookie(driver, city_name)
    soft_navigate(driver, wn_url, log)
    human_pause(2.0, 3.5)
    _sync_lagou_city_cookie(driver, city_name)
    try:
        current = driver.current_url or ""
        actual = _read_city_from_lagou_url(current)
        if city_name and city_name != "全国":
            if _lagou_url_matches_city(current, city_name):
                log(f"[拉勾网] URL 已包含城市 {city_name}")
            elif actual:
                log(
                    f"[拉勾网] 警告：URL 城市为「{actual}」，"
                    f"与配置「{city_name}」不一致，正在修正..."
                )
                soft_navigate(driver, wn_url, log)
                human_pause(1.5, 2.5)
            else:
                log(f"[拉勾网] URL 未带 city 参数，重新打开带城市的搜索页...")
                soft_navigate(driver, wn_url, log)
                human_pause(1.5, 2.5)
    except WebDriverException:
        pass
    return wn_url


def _set_react_input_value(driver, element, value: str) -> None:
    try:
        driver.execute_script(
            """
            const el = arguments[0];
            const value = arguments[1];
            const desc = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value'
            );
            if (desc && desc.set) desc.set.call(el, value);
            else el.value = value;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            """,
            element, value,
        )
    except WebDriverException:
        _human_type(element, value)


def _submit_lagou_search_via_js(driver, keyword: str) -> dict:
    script = """
    const keyword = arguments[0];
    function setValue(el, value) {
        const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
        if (desc && desc.set) desc.set.call(el, value);
        else el.value = value;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }
    const inputs = Array.from(document.querySelectorAll('input'));
    const hints = ['搜索', '职位', '关键词', '想找'];
    for (const el of inputs) {
        const type = (el.type || '').toLowerCase();
        if (['hidden', 'checkbox', 'radio', 'file'].includes(type)) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width < 40 || rect.height < 10) continue;
        const ph = (el.placeholder || '').toLowerCase();
        const id = (el.id || '').toLowerCase();
        const name = (el.name || '').toLowerCase();
        const hit = hints.some(h => ph.includes(h))
            || id.includes('search') || name === 'kd';
        if (!hit) continue;
        el.focus();
        setValue(el, keyword);
        const btn = document.querySelector(
            'input.search_button, button.search-btn, .search_button, .search-btn, '
            + '[class*="search-btn"], [class*="search"] button, [class*="Search"] button'
        );
        if (btn) {
            btn.click();
            return {ok: true, method: 'button'};
        }
        el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}));
        el.dispatchEvent(new KeyboardEvent('keypress', {key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}));
        el.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}));
        return {ok: true, method: 'enter'};
    }
    return {ok: false, count: inputs.length};
    """
    try:
        return driver.execute_script(script, keyword) or {}
    except WebDriverException:
        return {}


def _lagou_search_input(driver):
    return _find_visible_element(driver, LAGOU_SEARCH_INPUT_SELECTORS)


def _lagou_search_took_effect(driver, keyword: str, check_fn) -> bool:
    if check_fn(driver):
        return True
    try:
        url = driver.current_url or ""
        title = driver.title or ""
    except WebDriverException:
        return False
    if is_lagou_blocked_url(url, title) or is_lagou_waf_page(driver):
        return False
    if is_lagou_search_url(url, keyword, title) or is_lagou_search_url(url, "", title):
        return True
    return not is_lagou_home_url(url)


def _submit_lagou_search_via_keyboard(
    driver,
    keyword: str,
    log: Callable[[str], None],
) -> bool:
    """逐字键入 + 回车，适配 React 首页搜索框。"""
    search_input = _lagou_search_input(driver)
    if search_input is None:
        return False
    log("[拉勾网] 模拟键盘输入关键词并回车...")
    _human_click(driver, search_input)
    time.sleep(random.uniform(0.4, 0.8))
    try:
        search_input.send_keys(Keys.CONTROL, "a")
        time.sleep(0.1)
        search_input.send_keys(Keys.DELETE)
    except WebDriverException:
        try:
            search_input.clear()
        except WebDriverException:
            pass
    _human_type(search_input, keyword)
    time.sleep(random.uniform(0.6, 1.2))
    search_btn = _find_visible_element(driver, LAGOU_SEARCH_BTN_SELECTORS)
    if search_btn is not None and random.random() < 0.55:
        _human_click(driver, search_btn)
        log("[拉勾网] 已点击搜索按钮")
    else:
        search_input.send_keys(Keys.ENTER)
        log("[拉勾网] 已按回车提交搜索")
    return True


def _submit_lagou_search_via_ui(
    driver,
    keyword: str,
    log: Callable[[str], None],
) -> bool:
    search_input = _lagou_search_input(driver)
    if search_input is None:
        return False
    log("[拉勾网] 模拟点击搜索框并输入关键词...")
    _human_click(driver, search_input)
    time.sleep(random.uniform(0.3, 0.6))
    _human_type(search_input, keyword)
    time.sleep(random.uniform(0.5, 1.0))
    search_btn = _find_visible_element(driver, LAGOU_SEARCH_BTN_SELECTORS)
    if search_btn is not None:
        _human_click(driver, search_btn)
        log("[拉勾网] 已点击搜索按钮")
        return True
    try:
        search_input.send_keys(Keys.ENTER)
        log("[拉勾网] 已按回车提交搜索")
        return True
    except WebDriverException:
        return False


def _try_lagou_auto_search(
    driver,
    keyword: str,
    log: Callable[[str], None],
    check_fn,
    stop_check=None,
) -> bool:
    """多种方式自动搜索，直到离开首页或出现结果。"""
    attempts = (
        ("键盘输入", _submit_lagou_search_via_keyboard),
        ("点击搜索", _submit_lagou_search_via_ui),
    )
    for label, fn in attempts:
        if stop_check and stop_check():
            return False
        try:
            if not fn(driver, keyword, log):
                continue
        except WebDriverException:
            continue
        human_pause(2.0, 3.5)
        for _ in range(12):
            if stop_check and stop_check():
                return False
            if _lagou_search_took_effect(driver, keyword, check_fn):
                log(f"[拉勾网] 自动搜索成功（{label}）")
                return True
            time.sleep(0.7)
        log(f"[拉勾网] {label}未跳转，尝试下一种方式...")

    js_result = _submit_lagou_search_via_js(driver, keyword)
    if js_result.get("ok"):
        log(f"[拉勾网] 已通过页面脚本提交搜索 ({js_result.get('method', 'js')})")
        human_pause(2.0, 3.0)
        if _lagou_search_took_effect(driver, keyword, check_fn):
            return True
    return False


def ensure_lagou_page(driver, log: Callable[[str], None] = print) -> bool:
    try:
        url = driver.current_url or ""
        title = driver.title or ""
    except WebDriverException:
        return False
    if is_lagou_blocked_url(url, title):
        return False
    u = url.lower()
    if "lagou.com" in u:
        if u.rstrip("/").endswith("lagou.com") or "/wn" in u or is_lagou_search_url(url):
            return True
    log("[拉勾网] 正在打开首页...")
    soft_navigate(driver, "https://www.lagou.com/", log)
    return not is_lagou_blocked_url(driver.current_url or "", driver.title or "")


def resolve_lagou_referer(
    driver,
    keyword: str,
    city_name: str = "",
) -> str:
    try:
        current = (driver.current_url or "").strip()
        title = driver.title or ""
    except WebDriverException:
        current, title = "", ""
    if (
        current
        and "lagou.com" in current
        and not is_lagou_blocked_url(current, title)
        and _lagou_url_matches_city(current, city_name)
    ):
        return current
    return build_wn_search_url(keyword, city_name)


def is_lagou_home_url(url: str = "") -> bool:
    u = (url or "").lower().rstrip("/")
    if not u or "lagou.com" not in u:
        return False
    return (
        u.endswith("lagou.com")
        or u.endswith("lagou.com/wn")
        or u.endswith("www.lagou.com/wn")
    )


def _lagou_dom_has_job_cards(driver) -> bool:
    script = """
    const sels = [
        'li.con_list_item', '[class*="job-card"]', '[class*="JobCard"]',
        '[class*="position-item"]', '[class*="search-job"]',
        '[data-positionid]', '.item_con li'
    ];
    for (const s of sels) {
        for (const el of document.querySelectorAll(s)) {
            const r = el.getBoundingClientRect();
            if (r.height > 24 && r.width > 80) return true;
        }
    }
    return false;
    """
    try:
        return bool(driver.execute_script(script))
    except WebDriverException:
        return False


def _lagou_search_page_ready(driver, keyword: str = "") -> bool:
    """搜索 URL 且非验证页，并出现结果区或空结果提示。"""
    try:
        url = driver.current_url or ""
        title = driver.title or ""
    except WebDriverException:
        return False
    if is_lagou_blocked_url(url, title) or is_lagou_waf_page(driver):
        return False
    if not is_lagou_search_url(url, keyword, title) and not is_lagou_search_url(url, "", title):
        return False
    if _lagou_dom_has_job_cards(driver):
        return True
    from .lagou_pager import find_current_page_lagou_items

    if find_current_page_lagou_items(driver):
        return True
    try:
        for sel in (".totalNum", "span.totalNum", "[class*='totalNum']"):
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed() and (el.text or "").strip().isdigit():
                    return True
        for sel in (".search-no-result", ".empty-position", "[class*='no-result']"):
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed():
                    return True
    except WebDriverException:
        pass
    # 新版 wn/search 为 SPA，常不渲染经典 DOM；URL 已到搜索页即可走 Ajax
    return True


def has_lagou_results(driver, keyword: str = "", city_name: str = "") -> bool:
    """仅检查页面 DOM，等待阶段不调用 Ajax。"""
    if is_lagou_waf_page(driver):
        return False
    if _lagou_search_page_ready(driver, keyword):
        return True
    try:
        url = driver.current_url or ""
    except WebDriverException:
        return False
    if is_lagou_home_url(url):
        return False
    return False


def wait_for_lagou_results(
    driver,
    log: Callable[[str], None],
    has_results_fn: Callable,
    detect_captcha_fn: Optional[Callable[[], bool]] = None,
    on_captcha_fn: Optional[Callable[[], bool]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
    timeout: float = 60,
    keyword: str = "",
    city_name: str = "",
) -> bool:
    deadline = time.monotonic() + timeout
    last_status = 0.0
    while time.monotonic() < deadline:
        if stop_check and stop_check():
            return False
        if has_results_fn(driver):
            return True
        try:
            url = driver.current_url or ""
            title = driver.title or ""
        except WebDriverException:
            url, title = "", ""
        if is_lagou_blocked_url(url, title) or is_lagou_waf_page(driver) or (
            detect_captcha_fn and detect_captcha_fn()
        ):
            log("[拉勾网] 检测到验证页，请完成滑块后重试...")
            if on_captcha_fn and on_captcha_fn():
                time.sleep(random.uniform(2.0, 3.0))
                continue
            return False
        now = time.monotonic()
        if now - last_status >= 12:
            if is_lagou_home_url(url):
                log("[拉勾网] 自动搜索尚未跳转，程序继续等待...")
            else:
                log(f"[拉勾网] 等待页面就绪… {url[:85]} | {title[:30]}")
            last_status = now
        time.sleep(1.5)
    if is_lagou_waf_page(driver):
        return False
    return bool(has_results_fn(driver))


def navigate_to_lagou_search(
    driver,
    keyword: str,
    city_name: str = "",
    log: Callable[[str], None] = print,
    has_results_fn=None,
    detect_captcha_fn: Optional[Callable[[], bool]] = None,
    on_captcha_fn: Optional[Callable[[], bool]] = None,
    login_confirmation: Optional[Callable[[str, int], bool]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """模拟人工在首页搜索，避免 driver.get 直接跳转搜索 URL。"""
    check_fn = has_results_fn or (lambda d: has_lagou_results(d, keyword, city_name))

    if check_fn(driver):
        log("[拉勾网] 已在搜索结果页")
        return True

    if not ensure_lagou_page(driver, log):
        log("[拉勾网] 当前处于验证/登录页")
        if on_captcha_fn and on_captcha_fn():
            if not ensure_lagou_page(driver, log):
                return False
        else:
            return False

    _prepare_lagou_page(driver, log)
    lagou_browse_warmup(driver, log, stop_check=stop_check)
    _select_lagou_city(driver, city_name, log)
    get_pacer().wait_before_request(
        delay_range=CRAWL_REQUEST_DELAY, log=log, label="准备搜索",
    )

    wait_kwargs = dict(
        detect_captcha_fn=detect_captcha_fn,
        on_captcha_fn=on_captcha_fn,
        stop_check=stop_check,
    )

    log(f"[拉勾网] 程序将自动搜索「{keyword}」"
        f"{(' · ' + city_name) if city_name and city_name != '全国' else ''}"
        f"（无需手动操作）...")

    if _try_lagou_auto_search(
        driver, keyword, log, check_fn, stop_check=stop_check,
    ):
        try:
            cur = driver.current_url or ""
        except WebDriverException:
            cur = ""
        if _lagou_url_matches_city(cur, city_name) and check_fn(driver):
            log("[拉勾网] 搜索结果已加载")
            return True
        log("[拉勾网] 首页搜索未带上配置城市，改为打开指定城市搜索页...")

    _open_lagou_search_page(driver, keyword, city_name, log)

    if is_lagou_waf_page(driver) or (
        detect_captcha_fn and detect_captcha_fn()
    ):
        log("[拉勾网] 打开搜索页触发验证，请在浏览器完成滑块...")
        if not (on_captcha_fn and on_captcha_fn()):
            return False
        human_pause(2.0, 3.0)
        _open_lagou_search_page(driver, keyword, city_name, log)

    if check_fn(driver):
        log("[拉勾网] 已进入搜索页，将通过接口读取数据")
        return True

    if detect_captcha_fn and detect_captcha_fn():
        log("[拉勾网] 搜索触发验证，请完成滑块...")
        if on_captcha_fn and on_captcha_fn():
            human_pause(2.0, 3.0)
            _open_lagou_search_page(driver, keyword, city_name, log)
            if check_fn(driver):
                log("[拉勾网] 搜索结果已加载")
                return True

    if wait_for_lagou_results(driver, log, check_fn, timeout=15, **wait_kwargs):
        log("[拉勾网] 搜索结果已加载")
        return True

    return False


def is_rate_limited(data: Optional[dict]) -> bool:
    if not data:
        return True
    err = data.get("parseError") or data.get("error") or ""
    if isinstance(err, str) and is_lagou_waf_html(err):
        return True
    return False


def format_lagou_error(data: Optional[dict]) -> str:
    if not data:
        return "无响应"
    if is_rate_limited(data):
        return "请求被 WAF/限流拦截（需先完成浏览器滑块验证）"
    return data.get("error") or data.get("parseError") or "接口返回失败"


def extract_lagou_ajax_result(data: Optional[dict]) -> tuple[list, int, int]:
    """解析 Ajax 响应，返回 (职位列表, 总页数, 每页条数)。"""
    if not data or not data.get("success"):
        return [], 0, 0
    pr = data.get("content", {}).get("positionResult", {}) or {}
    positions = pr.get("result") or []
    total = int(pr.get("totalCount") or 0)
    page_size = int(pr.get("pageSize") or 15) or 15
    total_pages = (total + page_size - 1) // page_size if total else 0
    return positions, total_pages, page_size


def fetch_lagou_page(
    driver,
    keyword: str,
    page: int,
    city: str = "",
    referer: str = "",
    skip_pause: bool = False,
) -> dict:
    """在已验证浏览器上下文中请求拉勾 Ajax 接口。"""
    if not skip_pause:
        lagou_ajax_pause()
    first = "true" if page == 1 else "false"
    parts = [
        f"first={first}",
        f"pn={page}",
        f"kd={urllib.parse.quote(keyword)}",
    ]
    if city and city != "全国":
        parts.append(f"city={urllib.parse.quote(city)}")
    body = "&".join(parts)
    ref = referer or build_list_url(keyword, city)
    hdrs = _random_lagou_fetch_headers(ref)

    script = """
    const body = arguments[0];
    const referer = arguments[1];
    const ajaxUrl = arguments[2];
    const hdrs = arguments[3];
    const callback = arguments[arguments.length - 1];
    fetch(ajaxUrl, {
        method: "POST",
        headers: hdrs,
        body: body,
        credentials: "include",
    })
    .then(r => r.text())
    .then(t => {
        try { callback(JSON.parse(t)); }
        catch (e) { callback({success: false, parseError: t.slice(0, 200)}); }
    })
    .catch(e => callback({success: false, error: String(e)}));
    """
    return driver.execute_async_script(script, body, ref, AJAX_URL, hdrs)


def fetch_lagou_page_with_retry(
    driver,
    keyword: str,
    page: int,
    city: str,
    list_url: str,
    log: Callable[[str], None] = print,
    max_retries: int = LAGOU_AJAX_MAX_RETRIES,
    skip_pre_pause: bool = False,
) -> dict:
    """限流时指数退避重试，不刷新页面。"""
    last: dict = {}
    for attempt in range(max_retries):
        last = fetch_lagou_page(
            driver, keyword, page, city, referer=list_url,
            skip_pause=skip_pre_pause,
        )
        if last.get("success"):
            return last
        if not is_rate_limited(last):
            return last
        if attempt >= max_retries - 1:
            break
        wait = lagou_backoff_wait(attempt)
        log(
            f"[拉勾网] 第 {page} 页被限流，退避 {wait:.0f} 秒"
            f" (重试 {attempt + 2}/{max_retries})..."
        )
        time.sleep(wait)
        lagou_simulate_browse(driver)
    return last


def parse_lagou_positions(positions: list) -> List[CompanyInfo]:
    results: List[CompanyInfo] = []
    for p in positions:
        if not isinstance(p, dict):
            continue
        name = (p.get("companyFullName") or p.get("companyShortName") or "").strip()
        if not name:
            continue
        city_val = p.get("city") or ""
        district = p.get("district") or ""
        location = f"{city_val}{district}".strip() or "—"
        results.append(CompanyInfo(
            platform="拉勾网",
            name=name,
            industry=p.get("industryField") or "—",
            scale=p.get("companySize") or "—",
            stage="",
            description="",
            location=location,
            hot_jobs="",
            salary="",
            contact_person="",
            contact_info="",
        ))
    return results


def company_url_from_id(company_id) -> str:
    if company_id:
        return f"https://www.lagou.com/gongsi/{company_id}.html"
    return ""


def build_lagou_company_lookup(positions: list) -> dict:
    """按公司名建立 Ajax 字段索引，供 DOM 解析结果补全。"""
    lookup: dict = {}
    for p in positions:
        if not isinstance(p, dict):
            continue
        company_url = company_url_from_id(p.get("companyId"))
        payload = {
            "industry": (p.get("industryField") or "").strip(),
            "scale": (p.get("companySize") or "").strip(),
            "location": f"{p.get('city') or ''}{p.get('district') or ''}".strip(),
            "company_url": company_url,
        }
        for key in (p.get("companyFullName"), p.get("companyShortName")):
            if key:
                lookup[str(key).strip()] = payload
    return lookup


def enrich_lagou_companies(
    companies: List[CompanyInfo],
    lookup: dict,
) -> None:
    """用 Ajax 数据补全 DOM 解析缺失的行业/规模。"""
    if not companies or not lookup:
        return
    for company in companies:
        info = lookup.get(company.name)
        if not info:
            for name, data in lookup.items():
                if company.name in name or name in company.name:
                    info = data
                    break
        if not info:
            continue
        if company.industry in ("—", "") or company.industry == company.name:
            if info.get("industry") and info["industry"] != company.name:
                company.industry = info["industry"]
        if company.scale in ("—", ""):
            company.scale = info.get("scale") or "—"
        if company.location in ("—", "") and info.get("location"):
            company.location = info["location"]
