#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉勾网 — 通过百度搜索公司官网并获取联系人/联系方式。"""

from __future__ import annotations

import random
import re
import time
import urllib.parse
from typing import Callable, List, Optional, Set
from urllib.parse import urlparse

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from .browser import safe_get
from .lagou_api import EMAIL_RE, PHONE_RE
from .models import CompanyInfo

LABEL_PERSON_RE = re.compile(
    r"(?:招聘负责人|联系人|HR负责人|招聘联系人|负责人)[：:\s]*"
    r"([^\s，,|/\n]{2,12})",
)
LABEL_PHONE_RE = re.compile(
    r"(?:联系电话|联系方式|电话|手机|座机)[：:\s]*"
    r"([0-9][0-9\-\s]{6,18})",
)

PERSON_SELECTORS = (
    ".manager_name",
    ".recruiter-name",
    ".contact-name",
    ".hr_name",
    ".manager-list .name",
)

INFO_SELECTORS = (
    ".manager_phone",
    ".recruiter-phone",
    ".contact-phone",
    ".company_phone",
    ".tel",
    "a[href^='tel:']",
    "a[href^='mailto:']",
)

BAIDU_RESULT_CSS = "#content_left .result, #content_left .c-container"

SKIP_HOST_FRAGMENTS = (
    "lagou.com",
    "liepin.com",
    "zhaopin.com",
    "51job.com",
    "zhipin.com",
    "boss.com",
    "yingjiesheng.com",
    "jobui.com",
    "kanzhun.com",
    "baike.baidu.com",
    "zhidao.baidu.com",
    "tieba.baidu.com",
    "tianyancha.com",
    "qcc.com",
    "aiqicha.baidu.com",
    "baidu.com",
    "weibo.com",
    "zhihu.com",
    "douban.com",
    "map.baidu.com",
    "1688.com",
    "jd.com",
    "tmall.com",
    "taobao.com",
)


def build_baidu_search_url(company_name: str) -> str:
    query = f"{company_name} 官网 联系方式"
    return f"https://www.baidu.com/s?wd={urllib.parse.quote(query)}"


def _host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except ValueError:
        return ""


def _should_skip_host(host: str) -> bool:
    if not host:
        return True
    return any(fragment in host for fragment in SKIP_HOST_FRAGMENTS)


def _company_name_tokens(name: str) -> list[str]:
    core = re.sub(
        r"(有限责任公司|股份有限公司|有限公司|集团公司|集团|公司)$",
        "",
        name.strip(),
    )
    tokens = [t for t in re.split(r"[\s·\-—()（）]+", core) if len(t) >= 2]
    return tokens or [name[:4]]


def _score_official_link(title: str, company_name: str) -> int:
    score = 0
    if "官网" in title or "官方网站" in title or "首页" in title:
        score += 12
    if "招聘" in title or "求职" in title:
        score -= 8
    for token in _company_name_tokens(company_name):
        if token in title:
            score += 6
            break
    return score


def _baidu_serp_text(driver) -> str:
    chunks: list[str] = []
    try:
        for block in driver.find_elements(By.CSS_SELECTOR, BAIDU_RESULT_CSS):
            text = (block.text or "").strip()
            if text:
                chunks.append(text)
    except WebDriverException:
        pass
    if chunks:
        return "\n".join(chunks)
    try:
        left = driver.find_element(By.CSS_SELECTOR, "#content_left")
        return left.text or ""
    except WebDriverException:
        try:
            return driver.find_element(By.TAG_NAME, "body").text or ""
        except WebDriverException:
            return ""


def _link_from_result(block) -> tuple[str, str]:
    for sel in ("h3 a", ".t a", "a"):
        try:
            el = block.find_element(By.CSS_SELECTOR, sel)
            href = (el.get_attribute("href") or "").strip()
            title = (el.text or "").strip()
            if href and title:
                return href, title
        except WebDriverException:
            continue
    return "", ""


def pick_official_site_link(driver, company_name: str) -> str:
    """从百度搜索结果中挑选最像官网的链接。"""
    best_url = ""
    best_score = 0
    try:
        blocks = driver.find_elements(By.CSS_SELECTOR, BAIDU_RESULT_CSS)
    except WebDriverException:
        return ""

    for block in blocks[:12]:
        href, title = _link_from_result(block)
        if not href or not title:
            continue
        host = _host_of(href)
        if _should_skip_host(host):
            continue
        score = _score_official_link(title, company_name)
        if score > best_score:
            best_score = score
            best_url = href

    if best_url:
        return best_url

    for block in blocks[:8]:
        href, title = _link_from_result(block)
        if not href:
            continue
        if not _should_skip_host(_host_of(href)):
            return href
    return ""


def extract_contact_from_text(text: str) -> tuple[str, str]:
    person = ""
    info = ""

    if text:
        m = LABEL_PERSON_RE.search(text)
        if m:
            person = m.group(1).strip()
        m = LABEL_PHONE_RE.search(text)
        if m:
            info = re.sub(r"\s+", "", m.group(1))
        else:
            phone = PHONE_RE.search(text)
            if phone:
                info = phone.group(0)
            else:
                email = EMAIL_RE.search(text)
                if email:
                    info = email.group(0)

    return person or "—", info or "—"


def _first_text_on_page(driver, *selectors: str) -> str:
    for sel in selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if sel.startswith("a[href^='tel:']"):
                    href = el.get_attribute("href") or ""
                    if href.startswith("tel:"):
                        return href[4:].strip()
                if sel.startswith("a[href^='mailto:']"):
                    href = el.get_attribute("href") or ""
                    if href.startswith("mailto:"):
                        return href[7:].split("?")[0].strip()
                text = (el.text or "").strip()
                if text:
                    return text
        except WebDriverException:
            continue
    return ""


def parse_webpage_contact(driver) -> tuple[str, str]:
    """解析网页正文中的联系人、联系方式。"""
    person = _first_text_on_page(driver, *PERSON_SELECTORS)
    info = _first_text_on_page(driver, *INFO_SELECTORS)

    try:
        body = driver.find_element(By.TAG_NAME, "body").text or ""
    except WebDriverException:
        body = ""

    page_person, page_info = extract_contact_from_text(body)
    if person == "":
        person = page_person if page_person != "—" else ""
    if info == "":
        info = page_info if page_info != "—" else ""

    return person or "—", info or "—"


def fill_contacts_from_company_pages(
    driver,
    companies: List[CompanyInfo],
    return_url: str,
    visited_companies: Set[str],
    log: Callable[[str], None] = print,
    stop_check: Optional[Callable[[], bool]] = None,
) -> None:
    """百度搜索公司官网，补全联系人/联系方式，完成后回到列表页。"""
    if not companies:
        return

    restore_url = driver.current_url or return_url
    filled = 0

    for company in companies:
        if stop_check and stop_check():
            break

        name = (company.name or "").strip()
        if not name or name in visited_companies:
            continue
        visited_companies.add(name)

        log(f"[拉勾网] 百度搜索: {name}")
        safe_get(driver, build_baidu_search_url(name), log)
        time.sleep(random.uniform(1.5, 2.5))

        person, info = extract_contact_from_text(_baidu_serp_text(driver))

        if info == "—":
            official = pick_official_site_link(driver, name)
            if official:
                log(f"[拉勾网] 打开官网: {official}")
                safe_get(driver, official, log)
                time.sleep(random.uniform(1.5, 2.5))
                page_person, page_info = parse_webpage_contact(driver)
                if person == "—" and page_person != "—":
                    person = page_person
                if page_info != "—":
                    info = page_info

        if person != "—":
            company.contact_person = person
        if info != "—":
            company.contact_info = info
        if person != "—" or info != "—":
            filled += 1

        time.sleep(random.uniform(2.0, 3.5))

    if filled:
        log(f"[拉勾网] 百度搜索补全 {filled} 家联系信息")

    if restore_url and restore_url != driver.current_url:
        safe_get(driver, restore_url, log)
        time.sleep(random.uniform(1.0, 2.0))
