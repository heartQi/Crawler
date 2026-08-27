#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉勾网 Ajax 接口 — 职位列表由 positionAjax.json 动态加载。"""

from __future__ import annotations

import random
import re
import time
import urllib.parse
from typing import Callable, List, Optional

from .browser import safe_get
from .models import CompanyInfo

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
    """拉勾搜索页 URL（用于 Ajax Referer，不用于程序自动打开）。"""
    kw_seg = urllib.parse.quote(keyword)
    url = f"{LIST_URL.format(kw=kw_seg)}?fromSearch=true"
    if city and city != "全国":
        url += f"&city={urllib.parse.quote(city)}"
    if page > 1:
        url += f"&pn={page}"
    return url


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
    if "/wn/search" in u or "/jobs/list" in u or "kd=" in u or "key=" in u:
        if not keyword:
            return True
        decoded = urllib.parse.unquote(url)
        return (
            keyword in decoded
            or urllib.parse.quote(keyword) in url
            or keyword.replace(" ", "") in decoded.replace(" ", "")
        )
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
    """限流时刷新搜索页并重试。"""
    last: dict = {}
    for attempt in range(max_retries):
        last = fetch_lagou_page(driver, keyword, page, city, referer=list_url)
        if last.get("success"):
            return last
        if not is_rate_limited(last):
            return last
        if attempt >= max_retries - 1:
            break
        wait = 10 + attempt * 8 + random.uniform(2, 5)
        log(f"[拉勾网] 第 {page} 页被限流，{wait:.0f} 秒后刷新并重试 ({attempt + 2}/{max_retries})...")
        time.sleep(wait)
        safe_get(driver, list_url, log)
        time.sleep(random.uniform(2.5, 4.0))
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
