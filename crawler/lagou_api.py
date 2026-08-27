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
from .models import CompanyInfo
from .stealth import human_pause

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
    if any(kw in t for kw in ("访问验证", "安全验证", "人机验证", "验证中心")):
        return True
    return False


def is_lagou_search_url(url: str, keyword: str = "") -> bool:
    if not url or "lagou.com" not in url.lower():
        return False
    if is_lagou_blocked_url(url):
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
    "input[placeholder*='搜索职位']",
    "input[placeholder*='搜索']",
    "input[placeholder*='职位']",
    "input[placeholder*='关键词']",
    ".search-box input",
    ".search_input",
    ".top-search input",
    "[class*='Search'] input[type='text']",
    "header input[type='text']",
    "input[type='search']",
)
LAGOU_SEARCH_BTN_SELECTORS = (
    "input.search_button",
    "button.search-btn",
    ".search_button",
    ".search-btn",
    "[class*='search-btn']",
    "button[type='submit']",
)
LAGOU_CITY_TRIGGER_SELECTORS = (
    ".city_label",
    "#city_name",
    ".changeCity_text",
    "[class*='city-wrapper']",
    "[class*='change-city']",
    ".position-header .city",
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


def _select_lagou_city(driver, city_name: str, log: Callable[[str], None]) -> bool:
    if not city_name or city_name == "全国":
        return True
    trigger = _find_visible_element(driver, LAGOU_CITY_TRIGGER_SELECTORS)
    if trigger is not None:
        current = (trigger.text or "").strip()
        if city_name in current:
            return True
        _human_click(driver, trigger)
        time.sleep(random.uniform(0.4, 0.8))
    city_option_selectors = (
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
                log(f"[拉勾网] 已选择城市 {city_name}")
                time.sleep(random.uniform(0.5, 1.0))
                return True
        except WebDriverException:
            continue
    return False


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
            'input.search_button, button.search-btn, .search_button, .search-btn, [class*="search-btn"]'
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


def _submit_lagou_search_via_ui(
    driver,
    keyword: str,
    log: Callable[[str], None],
) -> bool:
    search_input = _find_visible_element(driver, LAGOU_SEARCH_INPUT_SELECTORS)
    if search_input is None:
        return False
    log("[拉勾网] 模拟点击搜索框并输入关键词...")
    _human_click(driver, search_input)
    time.sleep(random.uniform(0.3, 0.6))
    _set_react_input_value(driver, search_input, keyword)
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
    if current and "lagou.com" in current and not is_lagou_blocked_url(current, title):
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


def has_lagou_results(driver, keyword: str = "", city_name: str = "") -> bool:
    """仅检查页面 DOM，等待阶段不调用 Ajax。"""
    from .lagou_pager import find_current_page_lagou_items

    if find_current_page_lagou_items(driver):
        return True
    if _lagou_dom_has_job_cards(driver):
        return True
    try:
        url = driver.current_url or ""
    except WebDriverException:
        return False
    if is_lagou_home_url(url):
        return False
    return is_lagou_search_url(url, keyword) or is_lagou_search_url(url, "")


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
        if is_lagou_blocked_url(url, title) or (
            detect_captcha_fn and detect_captcha_fn()
        ):
            log("[拉勾网] 仍在验证页，请完成滑块后重试...")
            if on_captcha_fn and on_captcha_fn():
                time.sleep(random.uniform(2.0, 3.0))
                continue
            return False
        now = time.monotonic()
        if now - last_status >= 12:
            if is_lagou_home_url(url):
                log("[拉勾网] 仍在首页，请在 Chrome 搜索框输入关键词并回车…")
            else:
                log(f"[拉勾网] 等待搜索结果… {url[:85]} | {title[:30]}")
            last_status = now
        time.sleep(1.5)
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
    _select_lagou_city(driver, city_name, log)
    time.sleep(random.uniform(0.8, 1.5))

    submitted = _submit_lagou_search_via_ui(driver, keyword, log)
    if not submitted:
        js_result = _submit_lagou_search_via_js(driver, keyword)
        if js_result.get("ok"):
            log(f"[拉勾网] 已通过页面脚本提交搜索 ({js_result.get('method', 'js')})")
            submitted = True
        else:
            log("[拉勾网] 未找到搜索框，将尝试其他方式...")

    if submitted:
        log("[拉勾网] 等待搜索结果加载...")
        human_pause(1.5, 2.5)
        for _ in range(25):
            if stop_check and stop_check():
                return False
            if check_fn(driver):
                log("[拉勾网] 搜索结果已加载")
                return True
            if detect_captcha_fn and detect_captcha_fn():
                log("[拉勾网] 搜索触发验证，请完成滑块...")
                if on_captcha_fn and on_captcha_fn():
                    human_pause(2.0, 3.0)
                    continue
                return False
            time.sleep(0.8)

    wait_kwargs = dict(
        detect_captcha_fn=detect_captcha_fn,
        on_captcha_fn=on_captcha_fn,
        stop_check=stop_check,
    )
    if wait_for_lagou_results(driver, log, check_fn, timeout=45, **wait_kwargs):
        log("[拉勾网] 搜索结果已加载")
        return True

    wn_url = build_wn_search_url(keyword, city_name)
    log("[拉勾网] 首页搜索未出结果，尝试打开搜索页...")
    soft_navigate(driver, wn_url, log)
    if wait_for_lagou_results(driver, log, check_fn, timeout=40, **wait_kwargs):
        log("[拉勾网] 搜索结果已加载")
        return True

    return False


def is_rate_limited(data: Optional[dict]) -> bool:
    if not data:
        return True
    err = data.get("parseError") or data.get("error") or ""
    if isinstance(err, str) and ("<!DOCTYPE" in err or "<html" in err.lower()):
        return True
    return False


def format_lagou_error(data: Optional[dict]) -> str:
    if not data:
        return "无响应"
    if is_rate_limited(data):
        return "请求被限流（返回 HTML 拦截页）"
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
) -> dict:
    """在已验证浏览器上下文中请求拉勾 Ajax 接口。"""
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

    script = """
    const body = arguments[0];
    const referer = arguments[1];
    const ajaxUrl = arguments[2];
    const callback = arguments[arguments.length - 1];
    fetch(ajaxUrl, {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": referer,
        },
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
    return driver.execute_async_script(script, body, ref, AJAX_URL)


def fetch_lagou_page_with_retry(
    driver,
    keyword: str,
    page: int,
    city: str,
    list_url: str,
    log: Callable[[str], None] = print,
    max_retries: int = 3,
) -> dict:
    """限流时等待后重试，不刷新页面。"""
    last: dict = {}
    for attempt in range(max_retries):
        last = fetch_lagou_page(driver, keyword, page, city, referer=list_url)
        if last.get("success"):
            return last
        if not is_rate_limited(last):
            return last
        if attempt >= max_retries - 1:
            break
        wait = 12 + attempt * 10 + random.uniform(3, 6)
        log(f"[拉勾网] 第 {page} 页被限流，{wait:.0f} 秒后重试 ({attempt + 2}/{max_retries})...")
        time.sleep(wait)
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
