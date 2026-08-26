#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉勾网 Ajax 接口 — 职位列表由 positionAjax.json 动态加载。"""

from __future__ import annotations

import random
import time
import urllib.parse
from typing import Callable, List, Optional

from .models import CompanyInfo

LIST_URL = "https://www.lagou.com/jobs/list_{kw}"
AJAX_URL = "https://www.lagou.com/jobs/positionAjax.json?needAddtionalResult=false"


def build_list_url(keyword: str, city: str = "") -> str:
    kw_seg = urllib.parse.quote(keyword)
    url = f"{LIST_URL.format(kw=kw_seg)}?fromSearch=true"
    if city and city != "全国":
        url += f"&city={urllib.parse.quote(city)}"
    return url


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
        driver.get(list_url)
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
            stage=p.get("financeStage") or "—",
            description="",
            location=location,
            hot_jobs=p.get("positionName") or "—",
            salary=p.get("salary") or "—",
        ))
    return results
