#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""猎聘 — 拦截页面搜索接口或解析 DOM 获取职位数据。"""

from __future__ import annotations

import random
import secrets
import string
import time
import urllib.parse
from typing import Callable, List, Optional, TYPE_CHECKING

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .browser import safe_get
from .models import CompanyInfo

if TYPE_CHECKING:
    from threading import Event

    from .auth import Credentials

SEARCH_API = "https://api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job"
HOME = "https://www.liepin.com"
DEFAULT_DQ = "410"
CAPTURE_WAIT_TIMEOUT = 22
WOW_WAIT_TIMEOUT = 90
MANUAL_SEARCH_TIMEOUT = 300
_CDP_HOOK_FLAG = "_liepin_cdp_hook_installed"

LIEPIN_CITY_CODES = {
    "全国": "410",
    "北京": "010",
    "上海": "020",
    "广州": "050020",
    "深圳": "050090",
    "杭州": "070020",
    "成都": "090020",
    "南京": "060020",
    "武汉": "170020",
    "西安": "200020",
    "重庆": "040",
    "苏州": "060080",
    "天津": "030",
    "长沙": "180020",
    "郑州": "140020",
    "青岛": "120020",
    "大连": "210040",
    "厦门": "110020",
    "合肥": "150020",
}

LIEPIN_CAPTURE_HOOK = """
if (!window.__liepinCaptureInstalled) {
    window.__liepinCaptureInstalled = true;
    window.__liepinLastSearch = null;
    const saveLiepinSearch = (text) => {
        try {
            const data = JSON.parse(text);
            if (data && (data.flag === 1 || data.data)) {
                window.__liepinLastSearch = data;
            }
        } catch (e) {}
    };
    const origFetch = window.fetch;
    window.fetch = async function(...args) {
        const res = await origFetch.apply(this, args);
        try {
            const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
            if (url.includes('pc-search-job')) {
                saveLiepinSearch(await res.clone().text());
            }
        } catch (e) {}
        return res;
    };
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
        this.__liepinUrl = url || '';
        return origOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function(...args) {
        this.addEventListener('load', function() {
            const url = this.__liepinUrl || '';
            if (url.includes('pc-search-job') && this.responseText) {
                saveLiepinSearch(this.responseText);
            }
        });
        return origSend.apply(this, args);
    };
}
"""

LIEPIN_HOME_SEARCH_JS = """
const keyword = arguments[0];
const nativeSet = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
);
const setValue = (el, val) => {
    if (nativeSet && nativeSet.set) nativeSet.set.call(el, val);
    else el.value = val;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
};

function collectInputs(root, out) {
    root.querySelectorAll('input, textarea, [contenteditable="true"]').forEach((el) => {
        if (!out.includes(el)) out.push(el);
    });
    root.querySelectorAll('*').forEach((node) => {
        if (node.shadowRoot) collectInputs(node.shadowRoot, out);
    });
}

const all = [];
collectInputs(document, all);

let best = null;
let bestScore = 0;
for (const el of all) {
    const ph = (el.placeholder || el.getAttribute('placeholder') || '').toLowerCase();
    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
    const name = (el.name || '').toLowerCase();
    const cls = (el.className || '').toString().toLowerCase();
    const id = (el.id || '').toLowerCase();
    const type = (el.type || '').toLowerCase();
    let score = 0;
    if (ph.includes('搜索') || ph.includes('职位') || ph.includes('关键')) score += 14;
    if (name === 'key' || name.includes('keyword') || name.includes('search')) score += 12;
    if (cls.includes('search')) score += 8;
    if (id.includes('search')) score += 8;
    if (aria.includes('搜索') || aria.includes('职位')) score += 10;
    if (type === 'search' || type === 'text') score += 2;
    if (type === 'hidden' || type === 'password') score = 0;
    const r = el.getBoundingClientRect();
    if (r.width < 50 || r.height < 6) continue;
    if (score > bestScore) {
        bestScore = score;
        best = el;
    }
}

if (!best && all.length) {
    for (const el of all) {
        const type = (el.type || '').toLowerCase();
        if (type === 'hidden' || type === 'password' || type === 'checkbox') continue;
        const r = el.getBoundingClientRect();
        if (r.width >= 120 && r.top < 400) {
            best = el;
            bestScore = 1;
            break;
        }
    }
}

if (!best) {
    return { ok: false, reason: 'no_input', count: all.length };
}

try { best.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
best.focus();
if (best.isContentEditable) {
    best.textContent = keyword;
    best.dispatchEvent(new Event('input', { bubbles: true }));
} else {
    setValue(best, keyword);
}

const clickBtn = () => {
    const sels = [
        'button[data-selector="search-button"]',
        '[data-selector="search-button"]',
        '.search-btn', '.search-box button', '.header-search button',
        'button[type="submit"]', 'a.search-btn',
    ];
    for (const sel of sels) {
        const btn = document.querySelector(sel);
        if (btn && btn.offsetParent !== null) {
            btn.click();
            return true;
        }
    }
    return false;
};

if (!clickBtn()) {
    const form = best.closest('form');
    if (form) {
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
    } else {
        best.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true,
        }));
    }
}
return {
    ok: true,
    score: bestScore,
    count: all.length,
    placeholder: best.placeholder || '',
    name: best.name || '',
};
"""


def resolve_liepin_dq(city_name: str = "", city_code: str = "") -> str:
    """猎聘城市编码，如北京=010、全国=410。"""
    if city_code:
        return city_code
    if city_name in LIEPIN_CITY_CODES:
        return LIEPIN_CITY_CODES[city_name]
    if city_name and city_name != "全国":
        return city_name
    return DEFAULT_DQ


_ALPHANUM = string.ascii_lowercase + string.digits


def _random_ck_id() -> str:
    """猎聘 ckId：32 位小写字母+数字（与官网 JS 一致，非 hex）。"""
    return "".join(secrets.choice(_ALPHANUM) for _ in range(32))


def build_liepin_list_url(
    keyword: str,
    city_name: str = "",
    page: int = 0,
    city_code: str = "",
) -> str:
    """构造与猎聘前端一致的搜索页 URL，由页面自行请求接口。"""
    dq = resolve_liepin_dq(city_name, city_code)
    ck_id = _random_ck_id()
    params = {
        "city": dq,
        "dq": dq,
        "pubTime": "",
        "currentPage": max(0, page),
        "pageSize": "40",
        "key": keyword,
        "suggestTag": "",
        "workYearCode": "0",
        "compId": "",
        "compName": "",
        "compTag": "",
        "industry": "",
        "salaryCode": "",
        "jobKind": "",
        "compScale": "",
        "compKind": "",
        "compStage": "",
        "eduLevel": "",
        "otherCity": "",
        "ckId": ck_id,
        "skId": ck_id,
        "fkId": ck_id,
        "scene": "condition",
        "sfrom": "search_job_pc",
        "suggestId": "",
    }
    return f"{HOME}/zhaopin/?{urllib.parse.urlencode(params)}"


def install_liepin_capture_hook(driver) -> None:
    if not getattr(driver, _CDP_HOOK_FLAG, False):
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": LIEPIN_CAPTURE_HOOK},
            )
            setattr(driver, _CDP_HOOK_FLAG, True)
        except WebDriverException:
            pass
    try:
        driver.execute_script(LIEPIN_CAPTURE_HOOK)
    except WebDriverException:
        pass


def is_liepin_wow_page(url: str = "") -> bool:
    return "wow.liepin" in (url or "").lower()


def _is_liepin_home_url(url: str, title: str = "") -> bool:
    if is_liepin_login_page(url, title) or is_liepin_wow_page(url):
        return False
    parsed = urllib.parse.urlparse(url or "")
    host = (parsed.netloc or "").lower()
    path = parsed.path or "/"
    if not host.endswith("liepin.com"):
        return False
    return not path.startswith("/zhaopin") and "security" not in path


def is_liepin_blocked_page(url: str = "", title: str = "") -> bool:
    """登录页 / wow 拦截页（程序打开搜索链接触发）。"""
    return is_liepin_login_page(url, title) or is_liepin_wow_page(url)


def escape_to_liepin_home(
    driver,
    log: Callable[[str], None] = print,
) -> bool:
    """从 wow / 登录页退回猎聘首页。"""
    log("[猎聘] 正在返回猎聘首页...")
    for _ in range(3):
        try:
            driver.execute_script("window.history.back();")
            time.sleep(random.uniform(1.5, 2.5))
            url = driver.current_url or ""
            if _is_liepin_home_url(url, driver.title or ""):
                log("[猎聘] 已返回猎聘首页")
                return True
        except WebDriverException:
            break
    recover_liepin_tab(driver, HOME, log, reason="返回猎聘首页")
    try:
        url = driver.current_url or ""
        return _is_liepin_home_url(url, driver.title or "")
    except WebDriverException:
        return False


def ensure_liepin_session(
    driver,
    stop_event: Optional["Event"] = None,
    credentials: Optional["Credentials"] = None,
    login_confirmation: Optional[Callable[[str, int], bool]] = None,
    log: Callable[[str], None] = print,
) -> bool:
    """有凭据时尝试登录；已登录或无需登录则返回 True。"""
    from threading import Event

    from .accounts import resolve_credentials
    from .auth import LoginCoordinator

    event = stop_event or Event()
    auth = LoginCoordinator(driver, event, log)
    if auth.is_liepin_authenticated():
        log("[猎聘] 已登录")
        return True

    creds = resolve_credentials("liepin", credentials)
    if creds and (creds.username or creds.password):
        log("[猎聘] 检测到登录页，正在使用配置文件账号登录...")
        return auth.ensure_liepin_login(creds, login_confirmation)

    try:
        url = driver.current_url or ""
        title = driver.title or ""
    except WebDriverException:
        return True
    if is_liepin_blocked_page(url, title):
        log("[猎聘] 出现登录页，请在 .credentials.json 配置 liepin 账号密码")
        return False
    return True


def handle_liepin_blocked(
    driver,
    stop_event: Optional["Event"] = None,
    credentials: Optional["Credentials"] = None,
    login_confirmation: Optional[Callable[[str, int], bool]] = None,
    log: Callable[[str], None] = print,
) -> bool:
    """拦截页：优先尝试登录，失败则退回首页。"""
    if ensure_liepin_session(
        driver, stop_event, credentials, login_confirmation, log,
    ):
        try:
            url = driver.current_url or ""
            title = driver.title or ""
        except WebDriverException:
            return True
        if not is_liepin_blocked_page(url, title):
            return True
    return escape_to_liepin_home(driver, log)


def _on_liepin_search_page(driver, keyword: str = "") -> bool:
    try:
        cur = driver.current_url or ""
    except WebDriverException:
        return False
    return _is_liepin_search_url(cur, keyword)


def _is_liepin_search_url(url: str, keyword: str = "") -> bool:
    if not url or is_liepin_wow_page(url):
        return False
    if is_liepin_login_page(url):
        return False
    if "zhaopin" not in url.lower():
        return False
    if not keyword:
        return True
    decoded = urllib.parse.unquote(url)
    return (
        keyword in decoded
        or urllib.parse.quote(keyword) in url
        or "key=" in url
    )


COUNT_JOBS_JS = """
const box = document.querySelector('.job-list-box');
if (box) {
    let n = box.querySelectorAll('.job-card-pc-container').length;
    if (n > 0) return n;
    n = box.querySelectorAll(':scope > div').length;
    if (n > 0) return n;
}
return document.querySelectorAll(
    '[class*="job-card-pc"], [class*="job-card"], .job-list-item'
).length;
"""

EXTRACT_DOM_JS = """
const results = [];
const boxes = document.querySelectorAll(
    '.job-list-box > div, .job-list-box .job-card-pc-container, ' +
    '[class*="job-card-pc"], .job-list-box [class*="job-card"], .job-list-item'
);
boxes.forEach((el) => {
    const root = el.classList && el.classList.contains('job-card-pc-container') ? el : (
        el.querySelector('.job-card-pc-container') || el
    );
    if (!root) return;
    const pick = (...sels) => {
        for (const sel of sels) {
            const node = root.querySelector(sel);
            const text = (node && (node.innerText || node.textContent) || '').trim();
            if (text) return text;
        }
        return '';
    };
    const comp = pick(
        '[class*="company-name"] a', '[class*="company-name"]',
        '.company-name a', '.company-name', 'a[href*="/company/"]'
    );
    if (!comp) return;
    results.push({
        compName: comp,
        jobTitle: pick(
            '[class*="job-title"] a', '[class*="job-title"]',
            '.job-title-box .ellipsis-1', 'a[href*="/job/"]'
        ),
        salary: pick('[class*="job-salary"]', '[class*="salary"]', '.job-finance-info .tag'),
        location: pick('[class*="job-dq"]', '[class*="job-area"]', '.job-area'),
        industry: pick('[class*="company-tags"] span', '.company-info span'),
    });
});
return results;
"""


def _is_blank_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return not u or u == "about:blank" or u.startswith("about:")


def recover_liepin_tab(
    driver,
    url: str,
    log: Callable[[str], None] = print,
    reason: str = "",
) -> None:
    """空白页或离开猎聘时，在当前标签重新加载。"""
    try:
        cur = (driver.current_url or "").strip()
    except WebDriverException:
        cur = ""
    if not _is_blank_url(cur) and "liepin.com" in cur and url in cur:
        return
    if reason:
        log(f"[猎聘] {reason}，正在加载页面...")
    elif _is_blank_url(cur):
        log("[猎聘] 检测到空白页，正在重新加载...")
    else:
        log(f"[猎聘] 当前页面: {cur[:70] or '(空)'}，正在跳转...")
    safe_get(driver, url, log)
    time.sleep(random.uniform(2.0, 3.0))


def _focus_best_liepin_tab(driver) -> str:
    """切换到最相关的猎聘标签（优先搜索页）。"""
    best_handle = ""
    best_score = -100
    for handle in driver.window_handles:
        try:
            driver.switch_to.window(handle)
            url = (driver.current_url or "").strip()
        except WebDriverException:
            continue
        score = 0
        if _is_blank_url(url):
            score = -50
        elif "zhaopin" in url:
            score = 20
        elif "liepin.com" in url:
            score = 10
        if score > best_score:
            best_score = score
            best_handle = handle
    if best_handle:
        try:
            driver.switch_to.window(best_handle)
        except WebDriverException:
            pass
    try:
        return driver.current_url or ""
    except WebDriverException:
        return ""


def _dom_list_to_payload(dom_items: List[CompanyInfo], page: int) -> dict:
    return {
        "flag": 1,
        "data": {
            "pagination": {"totalPage": page},
            "data": {
                "jobCardList": [
                    {
                        "comp": {
                            "compName": c.name,
                            "compIndustry": c.industry,
                            "compScale": c.scale,
                            "compStage": c.stage,
                        },
                        "job": {
                            "title": c.hot_jobs,
                            "salary": c.salary,
                            "dq": c.location,
                        },
                    }
                    for c in dom_items
                ],
            },
        },
        "_from_dom": True,
    }


def _parse_dom_rows(rows: list) -> List[CompanyInfo]:
    results: List[CompanyInfo] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = (row.get("compName") or "").strip()
        if not name:
            continue
        results.append(CompanyInfo(
            platform="猎聘",
            name=name,
            industry=(row.get("industry") or "—").strip() or "—",
            scale="—",
            stage="—",
            description="",
            location=(row.get("location") or "—").strip() or "—",
            hot_jobs=(row.get("jobTitle") or "—").strip() or "—",
            salary=(row.get("salary") or "—").strip() or "—",
            contact_person="",
            contact_info="",
        ))
    return results


def extract_jobs_from_dom_fast(
    driver,
    log: Callable[[str], None] = print,
    wait_sec: float = 3,
) -> List[CompanyInfo]:
    """快速检测职位列表（用于轮询，避免长时间阻塞）。"""
    try:
        WebDriverWait(driver, wait_sec).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                ".job-list-box, [class*='job-card-pc'], [class*='job-card'], .job-list-item",
            )),
        )
    except TimeoutException:
        pass

    try:
        rows = driver.execute_script(EXTRACT_DOM_JS) or []
        results = _parse_dom_rows(rows)
        if results:
            return results
    except WebDriverException:
        pass

    try:
        count = int(driver.execute_script(COUNT_JOBS_JS) or 0)
    except WebDriverException:
        count = 0
    if count == 0:
        return []

    items = driver.find_elements(
        By.CSS_SELECTOR,
        ".job-list-box > div, .job-list-box .job-card-pc-container, "
        ".job-list-box [class*='job-card'], .job-list-item, [class*='job-card-pc']",
    )
    results: List[CompanyInfo] = []
    for item in items:
        try:
            info = _card_from_dom_item(item)
            if info:
                results.append(info)
        except WebDriverException:
            continue
    return results


def _scan_liepin_tabs_for_results(
    driver,
    keyword: str,
    page: int,
    log: Callable[[str], None] = print,
) -> dict:
    """扫描所有标签页，查找搜索结果。"""
    install_liepin_capture_hook(driver)
    try:
        original = driver.current_window_handle
    except WebDriverException:
        original = ""

    for handle in list(driver.window_handles):
        try:
            driver.switch_to.window(handle)
            install_liepin_capture_hook(driver)
            url = (driver.current_url or "").strip()
            title = driver.title or ""
        except WebDriverException:
            continue

        if is_liepin_login_page(url, title) or is_liepin_wow_page(url):
            continue

        data = read_captured_liepin(driver)
        if is_liepin_success(data):
            log(f"[猎聘] 标签页已拦截接口: {url[:90]}")
            return data

        if not _is_liepin_search_url(url, keyword):
            continue

        log(f"[猎聘] 发现搜索页，正在解析: {url[:90]}")
        data = _try_collect_search_page(driver, keyword, page, log, fast=True)
        if is_liepin_success(data):
            return data

    if original:
        try:
            driver.switch_to.window(original)
        except WebDriverException:
            pass
    return {}


def _try_collect_search_page(
    driver,
    keyword: str,
    page: int,
    log: Callable[[str], None] = print,
    fast: bool = False,
) -> dict:
    """在搜索结果页尝试：拦截 → URL 接口 → DOM。"""
    data = read_captured_liepin(driver)
    if is_liepin_success(data):
        return data

    cap_timeout = 2 if fast else 8
    data = wait_for_liepin_capture(driver, timeout=cap_timeout)
    if is_liepin_success(data):
        log("[猎聘] 已拦截页面搜索接口")
        return data

    if _is_liepin_search_url(driver.current_url or "", keyword):
        data = fetch_liepin_from_current_url(driver, page)
        if is_liepin_success(data):
            log("[猎聘] 搜索页接口返回数据")
            return data
        if data.get("msg") and not fast:
            log(f"[猎聘] 搜索页接口: {data.get('msg')}")

    dom_items = (
        extract_jobs_from_dom_fast(driver, log, wait_sec=2 if fast else 5)
        if fast else extract_jobs_from_dom(driver, log)
    )
    if dom_items:
        log(f"[猎聘] DOM 解析到 {len(dom_items)} 条")
        return _dom_list_to_payload(dom_items, page)
    return {}


def wait_for_liepin_user_search(
    driver,
    keyword: str,
    city_name: str = "",
    city_code: str = "",
    log: Callable[[str], None] = print,
    timeout: float = MANUAL_SEARCH_TIMEOUT,
    stop_event: Optional["Event"] = None,
    credentials: Optional["Credentials"] = None,
    login_confirmation: Optional[Callable[[str, int], bool]] = None,
) -> dict:
    """在首页等待用户手动搜索；有凭据时遇到登录页会自动尝试登录。"""
    install_liepin_capture_hook(driver)
    clear_liepin_capture(driver)
    _focus_best_liepin_tab(driver)
    handle_liepin_blocked(
        driver, stop_event, credentials, login_confirmation, log,
    )

    from .accounts import load_platform_credentials

    has_creds = bool(load_platform_credentials("liepin") or (
        credentials and (credentials.username or credentials.password)
    ))
    log("[猎聘] 请在 Chrome 首页手动搜索：")
    log(f"[猎聘]   1. 确认地址为 www.liepin.com 首页")
    log(f"[猎聘]   2. 在搜索框输入「{keyword}」并回车")
    if has_creds:
        log("[猎聘]   3. 若出现登录页，程序会自动填写账号；短信验证码请在浏览器完成")
    else:
        log("[猎聘]   3. 若出现登录页，请在 .credentials.json 配置 liepin 账号")
    log(f"[猎聘] 等待搜索结果（最多 {int(timeout)} 秒）...")

    deadline = time.monotonic() + timeout
    blocked_warned = False
    last_status = 0.0
    blank_recoveries = 0

    while time.monotonic() < deadline:
        _focus_best_liepin_tab(driver)
        data = _scan_liepin_tabs_for_results(driver, keyword, 1, log)
        if is_liepin_success(data):
            log("[猎聘] 已检测到搜索结果")
            return data

        try:
            url = driver.current_url or ""
            title = driver.title or ""
        except WebDriverException:
            time.sleep(1)
            continue

        if is_liepin_blocked_page(url, title):
            if not blocked_warned:
                if has_creds:
                    log("[猎聘] 检测到登录拦截页，正在尝试自动登录...")
                else:
                    log("[猎聘] 检测到登录拦截页，请配置 .credentials.json 中的 liepin 账号")
                blocked_warned = True
            handle_liepin_blocked(
                driver, stop_event, credentials, login_confirmation, log,
            )
            blocked_warned = False
            continue

        if _is_blank_url(url):
            if blank_recoveries < 3:
                blank_recoveries += 1
                recover_liepin_tab(
                    driver, HOME, log,
                    reason=f"页面空白（第 {blank_recoveries} 次恢复）",
                )
            continue

        now = time.monotonic()
        if now - last_status >= 15:
            tabs = []
            for handle in driver.window_handles:
                try:
                    driver.switch_to.window(handle)
                    tabs.append((driver.current_url or "")[:70])
                except WebDriverException:
                    tabs.append("(未知)")
            _focus_best_liepin_tab(driver)
            log(f"[猎聘] 监测中… 共 {len(tabs)} 个标签: {' | '.join(tabs)}")
            last_status = now

        time.sleep(2)

    return {
        "flag": 0,
        "msg": "等待超时。请在猎聘首页手动搜索；若反复出现登录页请配置 .credentials.json 或删除 .manual_browser",
    }


def wait_liepin_challenge_clear(
    driver,
    log: Callable[[str], None] = print,
    timeout: float = WOW_WAIT_TIMEOUT,
    stop_event: Optional["Event"] = None,
    credentials: Optional["Credentials"] = None,
    login_confirmation: Optional[Callable[[str, int], bool]] = None,
) -> bool:
    """wow / 登录拦截页：有凭据则尝试登录，否则退回首页。"""
    try:
        url = driver.current_url or ""
        title = driver.title or ""
    except WebDriverException:
        return False

    if not is_liepin_blocked_page(url, title):
        return True

    return handle_liepin_blocked(
        driver, stop_event, credentials, login_confirmation, log,
    )


def _prepare_liepin_home_page(driver, log: Callable[[str], None] = print) -> None:
    """等待首页 SPA 渲染完成。"""
    try:
        driver.execute_script("window.scrollTo(0, 0);")
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return document.readyState") == "complete",
        )
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script(
                "return document.querySelectorAll('input,textarea,[contenteditable=\"true\"]').length > 0;"
            ),
        )
    except TimeoutException:
        log("[猎聘] 首页加载较慢，继续尝试搜索...")
    time.sleep(random.uniform(1.5, 2.5))


def _submit_search_via_js(driver, keyword: str) -> dict:
    try:
        return driver.execute_script(LIEPIN_HOME_SEARCH_JS, keyword) or {}
    except WebDriverException:
        return {}


def _submit_search_in_iframes(driver, keyword: str) -> bool:
    try:
        iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
    except WebDriverException:
        return False
    for iframe in iframes:
        try:
            driver.switch_to.frame(iframe)
            result = _submit_search_via_js(driver, keyword)
            if result.get("ok"):
                return True
        except WebDriverException:
            pass
        finally:
            try:
                driver.switch_to.default_content()
            except WebDriverException:
                pass
    return False


def navigate_liepin_search_url(
    driver,
    keyword: str,
    city_name: str = "",
    city_code: str = "",
    log: Callable[[str], None] = print,
) -> bool:
    """兜底：在当前标签打开搜索页（可能触发验证页）。"""
    url = build_liepin_list_url(keyword, city_name, 0, city_code)
    log(f"[猎聘] 打开搜索页: {url[:90]}...")
    try:
        driver.execute_script("window.location.assign(arguments[0]);", url)
    except WebDriverException:
        safe_get(driver, url, log)
    time.sleep(random.uniform(2.5, 3.5))
    return True


def trigger_liepin_home_search(
    driver,
    keyword: str,
    city_name: str = "",
    city_code: str = "",
    log: Callable[[str], None] = print,
) -> bool:
    """在首页搜索框模拟人工输入并提交（由页面自行请求接口）。"""
    if not ensure_liepin_home_tab(driver, log):
        return False
    _prepare_liepin_home_page(driver, log)

    result = _submit_search_via_js(driver, keyword)
    if result.get("ok"):
        log(
            f"[猎聘] 已通过脚本提交搜索"
            f"（候选输入框 {result.get('count', 0)} 个）"
        )
        time.sleep(random.uniform(2.0, 3.0))
        return True

    if _submit_search_in_iframes(driver, keyword):
        log("[猎聘] 已在 iframe 内提交搜索")
        time.sleep(random.uniform(2.0, 3.0))
        return True

    input_selectors = (
        "input[data-selector='search-input']",
        "input[data-nick='search-input']",
        ".search-ipt input",
        ".search-box input",
        ".header-search input",
        ".home-search input",
        "input[placeholder*='搜索']",
        "input[placeholder*='职位']",
        "input[placeholder*='关键词']",
        "input[name='key']",
        "#search-input",
        "header input[type='text']",
    )
    btn_selectors = (
        "button[data-selector='search-button']",
        "[data-selector='search-button']",
        ".search-btn",
        ".search-box button",
        ".header-search button",
    )

    for sel in input_selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if not el.is_enabled():
                        continue
                except WebDriverException:
                    continue
                try:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", el,
                    )
                    ActionChains(driver).move_to_element(el).pause(
                        random.uniform(0.2, 0.5),
                    ).click(el).perform()
                except WebDriverException:
                    try:
                        driver.execute_script("arguments[0].click();", el)
                    except WebDriverException:
                        continue
                time.sleep(random.uniform(0.3, 0.6))
                try:
                    el.clear()
                except WebDriverException:
                    pass
                for ch in keyword:
                    el.send_keys(ch)
                    time.sleep(random.uniform(0.04, 0.12))
                time.sleep(random.uniform(0.4, 0.8))
                clicked = False
                for bsel in btn_selectors:
                    for btn in driver.find_elements(By.CSS_SELECTOR, bsel):
                        try:
                            if not btn.is_enabled():
                                continue
                            driver.execute_script("arguments[0].click();", btn)
                            clicked = True
                            break
                        except WebDriverException:
                            continue
                    if clicked:
                        break
                if not clicked:
                    el.send_keys(Keys.ENTER)
                log("[猎聘] 已在首页提交搜索")
                time.sleep(random.uniform(2.0, 3.0))
                return True
        except WebDriverException:
            continue

    count = result.get("count", 0)
    log(f"[猎聘] 未找到首页搜索框（检测到 {count} 个输入框），尝试直接打开搜索页...")
    navigate_liepin_search_url(driver, keyword, city_name, city_code, log)
    return True


def is_liepin_login_page(url: str = "", title: str = "") -> bool:
    """猎聘登录/通行证/wow 拦截页（搜索无需登录）。"""
    u = (url or "").lower()
    t = (title or "").strip()
    if is_liepin_wow_page(u):
        return True
    if "passport.liepin" in u or "account.liepin" in u:
        return True
    if "liepin.com" in u and ("login" in u or "signin" in u):
        return True
    if t == "登录" or ("登录" in t and "猎聘" in t):
        return True
    return False


def liepin_api_requires_login(data: Optional[dict]) -> bool:
    if not data:
        return False
    text = " ".join(
        str(data.get(k) or "")
        for k in ("msg", "error", "parseError")
    ).lower()
    return any(k in text for k in ("登录", "login", "未登录", "请先登"))


def ensure_liepin_home_tab(
    driver,
    log: Callable[[str], None] = print,
    stop_event: Optional["Event"] = None,
    credentials: Optional["Credentials"] = None,
    login_confirmation: Optional[Callable[[str, int], bool]] = None,
) -> bool:
    """确保在 www.liepin.com 首页；有凭据时可在登录页自动登录。"""

    def _is_home(url: str, title: str = "") -> bool:
        return _is_liepin_home_url(url, title)

    for handle in driver.window_handles:
        try:
            driver.switch_to.window(handle)
            url = (driver.current_url or "").strip()
            title = driver.title or ""
        except WebDriverException:
            continue
        if _is_home(url, title):
            log("[猎聘] 使用猎聘首页标签")
            return True

    # 有猎聘标签但在登录页：退回首页，不新开标签
    for handle in driver.window_handles:
        try:
            driver.switch_to.window(handle)
            url = (driver.current_url or "").strip()
        except WebDriverException:
            continue
        if "liepin.com" in url and not url.startswith("about:"):
            if is_liepin_blocked_page(url, driver.title or ""):
                log("[猎聘] 当前在登录页，正在尝试登录...")
                if handle_liepin_blocked(
                    driver, stop_event, credentials, login_confirmation, log,
                ):
                    url = driver.current_url or ""
                    if _is_home(url, driver.title or ""):
                        return True
            else:
                safe_get(driver, HOME, log)
                time.sleep(random.uniform(2.0, 3.0))
                url = driver.current_url or ""
                if _is_home(url, driver.title or ""):
                    return True
            if is_liepin_login_page(url, driver.title or ""):
                log("[猎聘] 仍停留在登录页，请检查 .credentials.json 中的 liepin 账号")
                return False
            break

    log("[猎聘] 打开猎聘首页...")
    try:
        _focus_best_liepin_tab(driver)
        recover_liepin_tab(driver, HOME, log)
        url = driver.current_url or ""
        title = driver.title or ""
        if _is_home(url, title):
            return True
        if is_liepin_login_page(url, title):
            log("[猎聘] 被导向登录页，请配置 .credentials.json 中的 liepin 账号后重试")
            return False
        if "wow.liepin" in url:
            log("[猎聘] 被重定向到验证页，请关闭 Chrome 并删除 .manual_browser 后重试")
    except WebDriverException:
        pass
    return False


def fetch_liepin_api(
    driver,
    keyword: str,
    page: int,
    city_name: str = "",
    city_code: str = "",
) -> dict:
    """在浏览器上下文请求搜索接口（自动尝试多种 scene / 字段组合）。"""
    dq = resolve_liepin_dq(city_name, city_code)
    referer = build_liepin_list_url(keyword, city_name, max(0, page - 1), city_code)
    script = """
    const keyword = arguments[0];
    const pageNum = arguments[1];
    const dq = arguments[2];
    const referer = arguments[3];
    const apiUrl = arguments[4];
    const callback = arguments[arguments.length - 1];

    const randId = (n) => {
        const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
        let s = '';
        for (let i = 0; i < n; i++) s += chars[Math.floor(Math.random() * chars.length)];
        return s;
    };
    const readSessionIds = () => {
        let sk = '', fk = '';
        try {
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i) || '';
                const v = localStorage.getItem(k) || '';
                if (/sk/i.test(k) && v.length >= 16) sk = v.slice(0, 32);
                if (/fk/i.test(k) && v.length >= 16) fk = v.slice(0, 32);
            }
        } catch (e) {}
        const ck = randId(32);
        return { ck, sk: sk || ck, fk: fk || ck };
    };

    const xsrfMatch = document.cookie.match(/(?:^|;\\s*)XSRF-TOKEN=([^;]+)/);
    const xsrf = xsrfMatch ? decodeURIComponent(xsrfMatch[1]) : '';
    const baseHeaders = {
        'Content-Type': 'application/json;charset=UTF-8',
        'Accept': 'application/json, text/plain, */*',
        'X-Client-Type': 'web',
        'X-Requested-With': 'XMLHttpRequest',
        'X-Fscp-Std-Info': '{"client_id": "40108"}',
        'X-Fscp-Version': '1.1',
        'Referer': referer,
        'Origin': 'https://www.liepin.com',
    };
    if (xsrf) baseHeaders['X-Xsrf-Token'] = xsrf;

    const ids = readSessionIds();
    const curPage = String(Math.max(0, pageNum - 1));
    const baseForm = {
        city: dq,
        dq: dq,
        pubTime: '',
        currentPage: curPage,
        pageSize: '40',
        key: keyword,
        suggestTag: '',
        workYearCode: '0',
        compId: '',
        compName: '',
        compTag: '',
        industry: '',
        salary: '',
        jobKind: '',
        compScale: '',
        compKind: '',
        compStage: '',
        eduLevel: '',
        otherCity: '',
    };

    const variants = [
        {
            scene: 'condition',
            passExtra: { sfrom: 'search_job_pc', suggestId: '', suggest: null },
        },
        {
            scene: 'input',
            passExtra: { sfrom: 'search_job_pc', suggestId: '', suggest: null, inputFrom: 'www_index' },
        },
        {
            scene: 'page',
            passExtra: { sfrom: 'search_job_pc' },
        },
    ];

    const postOnce = (variant) => fetch(apiUrl, {
        method: 'POST',
        headers: baseHeaders,
        body: JSON.stringify({
            data: {
                mainSearchPcConditionForm: { ...baseForm },
                passThroughForm: {
                    scene: variant.scene,
                    ckId: ids.ck,
                    skId: ids.sk,
                    fkId: ids.fk,
                    ...variant.passExtra,
                },
            },
        }),
        credentials: 'include',
    }).then(r => r.text()).then(t => {
        try { return JSON.parse(t); }
        catch (e) { return { flag: 0, parseError: t.slice(0, 300) }; }
    });

    const ok = (data) => {
        if (!data || data.flag !== 1) return false;
        const list = (((data.data || {}).data || {}).jobCardList) || [];
        return list.length > 0;
    };

    (async () => {
        let last = { flag: 0, msg: '无响应' };
        for (const variant of variants) {
            try {
                last = await postOnce(variant);
                if (ok(last)) {
                    callback(last);
                    return;
                }
            } catch (e) {
                last = { flag: 0, error: String(e) };
            }
        }
        callback(last);
    })();
    """
    try:
        driver.set_script_timeout(45)
        return driver.execute_async_script(
            script, keyword, page, dq, referer, SEARCH_API,
        )
    except WebDriverException as exc:
        return {"flag": 0, "error": str(exc)}


def fetch_liepin_from_current_url(driver, page: int) -> dict:
    """在搜索页用地址栏参数请求接口（与页面行为一致）。"""
    script = """
    const pageNum = arguments[0];
    const apiUrl = arguments[1];
    const callback = arguments[arguments.length - 1];
    const p = new URLSearchParams(location.search);
    if (pageNum > 1) p.set('currentPage', String(pageNum - 1));
    const pick = (k, d='') => (p.get(k) !== null && p.get(k) !== undefined) ? p.get(k) : d;
    const randId = () => {
        const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
        let s = '';
        for (let i = 0; i < 32; i++) s += chars[Math.floor(Math.random() * chars.length)];
        return s;
    };
    const dq = pick('dq', pick('city', '410'));
    const ckId = pick('ckId') || randId();
    const body = {
        data: {
            mainSearchPcConditionForm: {
                city: pick('city', dq),
                dq: dq,
                pubTime: pick('pubTime'),
                currentPage: pick('currentPage', '0'),
                pageSize: pick('pageSize', '40'),
                key: pick('key'),
                suggestTag: pick('suggestTag'),
                workYearCode: pick('workYearCode', '0'),
                compId: pick('compId'),
                compName: pick('compName'),
                compTag: pick('compTag'),
                industry: pick('industry'),
                salary: pick('salary', pick('salaryCode')),
                jobKind: pick('jobKind'),
                compScale: pick('compScale'),
                compKind: pick('compKind'),
                compStage: pick('compStage'),
                eduLevel: pick('eduLevel'),
                otherCity: pick('otherCity'),
            },
            passThroughForm: {
                scene: pick('scene', 'condition'),
                ckId: ckId,
                skId: pick('skId', ckId),
                fkId: pick('fkId', ckId),
                sfrom: pick('sfrom', 'search_job_pc'),
                suggestId: pick('suggestId'),
                suggest: null,
            },
        },
    };
    const xsrfMatch = document.cookie.match(/(?:^|;\\s*)XSRF-TOKEN=([^;]+)/);
    const xsrf = xsrfMatch ? decodeURIComponent(xsrfMatch[1]) : '';
    const headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'Accept': 'application/json, text/plain, */*',
        'X-Client-Type': 'web',
        'X-Requested-With': 'XMLHttpRequest',
        'X-Fscp-Std-Info': '{"client_id": "40108"}',
        'X-Fscp-Version': '1.1',
        'Referer': location.href,
        'Origin': 'https://www.liepin.com',
    };
    if (xsrf) headers['X-Xsrf-Token'] = xsrf;
    fetch(apiUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        credentials: 'include',
    })
    .then(r => r.text())
    .then(t => {
        try { callback(JSON.parse(t)); }
        catch (e) { callback({flag: 0, parseError: t.slice(0, 300)}); }
    })
    .catch(e => callback({flag: 0, error: String(e)}));
    """
    try:
        driver.set_script_timeout(30)
        return driver.execute_async_script(script, page, SEARCH_API)
    except WebDriverException as exc:
        return {"flag": 0, "error": str(exc)}


def _collect_after_search_trigger(
    driver,
    keyword: str,
    page: int,
    log: Callable[[str], None] = print,
) -> dict:
    """自动提交后的采集（优先抢在跳转前拦截接口）。"""
    data = wait_for_liepin_capture(driver, timeout=6)
    if is_liepin_success(data):
        log("[猎聘] 已拦截页面搜索接口")
        return data

    if not wait_liepin_challenge_clear(driver, log):
        return wait_for_liepin_user_search(driver, keyword, log=log)

    return _try_collect_search_page(driver, keyword, page, log)


def capture_liepin_via_search_page(
    driver,
    keyword: str,
    city_name: str = "",
    city_code: str = "",
    page: int = 1,
    log: Callable[[str], None] = print,
) -> dict:
    """首页模拟搜索，由页面自行加载结果（不直接跳转 URL）。"""
    install_liepin_capture_hook(driver)
    clear_liepin_capture(driver)
    if not trigger_liepin_home_search(driver, keyword, city_name, city_code, log):
        return {"flag": 0, "msg": "无法发起搜索"}
    return _collect_after_search_trigger(driver, keyword, page, log)


def navigate_to_liepin_search(
    driver,
    keyword: str,
    city_name: str = "",
    city_code: str = "",
    page: int = 1,
    log: Callable[[str], None] = print,
    stop_event: Optional["Event"] = None,
    credentials: Optional["Credentials"] = None,
    login_confirmation: Optional[Callable[[str, int], bool]] = None,
) -> bool:
    """优先接口；否则等待用户在浏览器手动搜索。"""
    install_liepin_capture_hook(driver)
    clear_liepin_capture(driver)

    if not ensure_liepin_home_tab(
        driver, log, stop_event, credentials, login_confirmation,
    ):
        return False

    if _on_liepin_search_page(driver, keyword):
        log("[猎聘] 已在搜索结果页")
        data = _try_collect_search_page(driver, keyword, page, log)
    else:
        log("[猎聘] 尝试接口查询...")
        data = fetch_liepin_api(driver, keyword, page, city_name, city_code)
        if is_liepin_success(data):
            log("[猎聘] 接口返回职位数据")
        else:
            if data.get("msg"):
                log(f"[猎聘] 接口: {data.get('msg')}")
            log("[猎聘] 请在浏览器首页手动搜索...")
            data = wait_for_liepin_user_search(
                driver, keyword, city_name, city_code, log,
                stop_event=stop_event,
                credentials=credentials,
                login_confirmation=login_confirmation,
            )

    if is_liepin_success(data):
        try:
            driver.execute_script(
                "window.__liepinLastSearch = arguments[0];", data,
            )
        except WebDriverException:
            pass
        return True
    if data.get("msg"):
        log(f"[猎聘] {data.get('msg')}")
    return False


def collect_liepin_page_data(
    driver,
    keyword: str,
    page: int,
    city_name: str = "",
    city_code: str = "",
    log: Callable[[str], None] = print,
) -> dict:
    """收集一页：缓存 → 接口 → 拦截 → DOM。"""
    data = read_captured_liepin(driver)
    if is_liepin_success(data):
        return data

    log(
        f"[猎聘] 请求第 {page} 页 "
        f"(city={resolve_liepin_dq(city_name, city_code)})..."
    )
    if _on_liepin_search_page(driver, keyword):
        data = fetch_liepin_from_current_url(driver, page)
        if is_liepin_success(data):
            return data
        if data.get("msg"):
            log(f"[猎聘] 接口: {data.get('msg')}")
    data = fetch_liepin_api(driver, keyword, page, city_name, city_code)
    if is_liepin_success(data):
        try:
            driver.execute_script(
                "window.__liepinLastSearch = arguments[0];", data,
            )
        except WebDriverException:
            pass
        return data
    if data.get("msg"):
        log(f"[猎聘] 接口: {data.get('msg')}")

    data = wait_for_liepin_capture(driver, timeout=8)
    if is_liepin_success(data):
        return data

    dom_items = extract_jobs_from_dom(driver, log)
    if dom_items:
        return {
            "flag": 1,
            "data": {
                "pagination": {"totalPage": page},
                "data": {
                    "jobCardList": [
                        {
                            "comp": {
                                "compName": c.name,
                                "compIndustry": c.industry,
                                "compScale": c.scale,
                                "compStage": c.stage,
                            },
                            "job": {
                                "title": c.hot_jobs,
                                "salary": c.salary,
                                "dq": c.location,
                            },
                        }
                        for c in dom_items
                    ],
                },
            },
            "_from_dom": True,
        }
    return data


def clear_liepin_capture(driver) -> None:
    try:
        driver.execute_script("window.__liepinLastSearch = null;")
    except WebDriverException:
        pass


def read_captured_liepin(driver) -> dict:
    try:
        data = driver.execute_script("return window.__liepinLastSearch;")
        return data if isinstance(data, dict) else {}
    except WebDriverException:
        return {}


def wait_for_liepin_capture(driver, timeout: float = CAPTURE_WAIT_TIMEOUT) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = read_captured_liepin(driver)
        if is_liepin_success(data):
            return data
        time.sleep(0.4)
    return read_captured_liepin(driver)


def load_liepin_search_page(
    driver,
    keyword: str,
    page: int,
    city_name: str = "",
    city_code: str = "",
    log: Callable[[str], None] = print,
) -> dict:
    """搜索页 URL 接口 → 手动接口。"""
    if _on_liepin_search_page(driver, keyword):
        data = fetch_liepin_from_current_url(driver, page)
        if is_liepin_success(data):
            log(f"[猎聘] 接口返回第 {page} 页数据")
            return data
        if data.get("msg"):
            log(f"[猎聘] 接口: {data.get('msg')}")
    data = fetch_liepin_api(driver, keyword, page, city_name, city_code)
    if is_liepin_success(data):
        log(f"[猎聘] 接口返回第 {page} 页数据")
        return data
    if data.get("msg"):
        log(f"[猎聘] 接口: {data.get('msg')}")
    return data


def is_liepin_success(data: Optional[dict]) -> bool:
    if not data or data.get("flag") != 1:
        return False
    inner = data.get("data") or {}
    payload = inner.get("data") or {}
    return bool(payload.get("jobCardList"))


def format_liepin_error(data: Optional[dict]) -> str:
    if not data:
        return "无响应（页面未发起搜索接口或仍在加载）"
    if data.get("parseError"):
        return f"返回非 JSON：{str(data['parseError'])[:80]}"
    if data.get("error"):
        return str(data["error"])
    return str(data.get("msg") or f"flag={data.get('flag')}")


def parse_liepin_positions(cards: list) -> List[CompanyInfo]:
    results: List[CompanyInfo] = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        comp = card.get("comp") or {}
        job = card.get("job") or {}
        name = (comp.get("compName") or "").strip()
        if not name:
            continue
        results.append(CompanyInfo(
            platform="猎聘",
            name=name,
            industry=(comp.get("compIndustry") or "—").strip() or "—",
            scale=(comp.get("compScale") or "—").strip() or "—",
            stage=(comp.get("compStage") or "—").strip() or "—",
            description="",
            location=(job.get("dq") or "—").strip() or "—",
            hot_jobs=(job.get("title") or "—").strip() or "—",
            salary=(job.get("salary") or "—").strip() or "—",
            contact_person="",
            contact_info="",
        ))
    return results


def _card_from_dom_item(item) -> Optional[CompanyInfo]:
    def _text(*selectors: str) -> str:
        for sel in selectors:
            try:
                for el in item.find_elements(By.CSS_SELECTOR, sel):
                    text = (el.text or "").strip()
                    if text:
                        return text
            except WebDriverException:
                continue
        return ""

    comp = _text(
        "[class*='company-name'] a",
        "[class*='company-name']",
        ".company-name a",
        ".company-name",
        ".comp-name a",
        ".comp-name",
    )
    if not comp:
        return None

    job = _text(
        "[class*='job-title'] a",
        "[class*='job-title']",
        ".job-title-box .ellipsis-1",
        ".job-name a",
        ".job-name",
    )
    salary = _text(
        "[class*='job-salary']",
        "[class*='salary']",
        ".job-finance-info .tag",
    )
    location = _text(
        "[class*='job-dq']",
        "[class*='job-area']",
        ".job-area",
        ".job-detail .dq",
    )

    industry = scale = ""
    for el in item.find_elements(
        By.CSS_SELECTOR,
        ".company-info span, [class*='company-info'] span, "
        "[class*='company-tags'] span",
    ):
        text = (el.text or "").strip()
        if not text:
            continue
        if not industry:
            industry = text
        elif not scale:
            scale = text

    return CompanyInfo(
        platform="猎聘",
        name=comp,
        industry=industry or "—",
        scale=scale or "—",
        stage="—",
        description="",
        location=location or "—",
        hot_jobs=job or "—",
        salary=salary or "—",
        contact_person="",
        contact_info="",
    )


def extract_jobs_from_dom(driver, log: Callable[[str], None] = print) -> List[CompanyInfo]:
    """从已渲染的 .job-list-box 解析职位。"""
    try:
        WebDriverWait(driver, CAPTURE_WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".job-list-box")),
        )
    except TimeoutException:
        log("[猎聘] 未找到 .job-list-box 容器")
        return []

    items = driver.find_elements(By.CSS_SELECTOR, ".job-list-box > div")
    if not items:
        items = driver.find_elements(
            By.CSS_SELECTOR,
            ".job-list-box .job-card-pc-container, "
            ".job-list-box [class*='job-card']",
        )

    results: List[CompanyInfo] = []
    for item in items:
        try:
            if not item.is_displayed():
                continue
            info = _card_from_dom_item(item)
            if info:
                results.append(info)
        except WebDriverException:
            continue
    return results


def fetch_liepin_page_with_retry(
    driver,
    keyword: str,
    page: int,
    city_name: str,
    city_code: str,
    list_url: str,
    log: Callable[[str], None] = print,
    max_retries: int = 2,
) -> dict:
    """在搜索页翻页：URL 接口 → 手动接口。"""
    last: dict = {}
    for attempt in range(max_retries):
        if _on_liepin_search_page(driver, keyword):
            last = fetch_liepin_from_current_url(driver, page)
            if is_liepin_success(last):
                return last
        last = fetch_liepin_api(driver, keyword, page, city_name, city_code)
        if is_liepin_success(last):
            return last
        if liepin_api_requires_login(last):
            log("[猎聘] 接口要求登录，职位搜索无需账号")
            return last
        if attempt < max_retries - 1:
            wait = 3 + attempt * 2
            log(f"[猎聘] 第 {page} 页接口失败，{wait} 秒后重试 ({attempt + 2}/{max_retries})...")
            time.sleep(wait)
    return last
