#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
各平台的页面解析函数（与爬虫引擎解耦，便于单独更新选择器）
"""

from __future__ import annotations

import json
import re

from selenium.webdriver.common.by import By

from .models import CompanyInfo

CONTACT_PHONE_RE = re.compile(
    r"1[3-9]\d{9}|0\d{2,3}[-\s]?\d{7,8}",
)
CONTACT_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def _extract_contact_from_item(item) -> tuple[str, str]:
    """从卡片 DOM 尝试提取联系人、电话/邮箱（仅用精确选择器，避免卡顿）。"""
    person = _first_text(
        item,
        ".publisher_name a",
        ".publisher_name",
        ".hr_name",
        ".recruiter-name",
        ".boss-name",
        ".companyinfo__staff",
    )
    info = _first_text(item, ".mobile", ".tel", ".phone")
    if not info:
        text = item.text or ""
        phone = CONTACT_PHONE_RE.search(text)
        if phone:
            info = phone.group(0)
        else:
            email = CONTACT_EMAIL_RE.search(text)
            if email:
                info = email.group(0)
    return person or "—", info or "—"


def parse_zhilian_item(item) -> CompanyInfo | None:
    """解析智联招聘单条职位卡片"""
    name_el      = item.find_elements(By.CSS_SELECTOR, ".companyinfo__name, .companyinfo a, [class*=companyname], .company-name")
    job_el       = item.find_elements(By.CSS_SELECTOR, ".jobinfo__name, .job-name, .job-title, [class*=jobname]")
    salary_el    = item.find_elements(By.CSS_SELECTOR, ".jobinfo__salary, .salary, [class*=salary]")
    loc_el       = item.find_elements(By.CSS_SELECTOR, ".jobinfo__demand__item--workaddress, .job-area, [class*=address]")
    compinfo_els = item.find_elements(By.CSS_SELECTOR, ".companyinfo__demand__item, [class*=companyinfo] [class*=item]")

    comp_name = name_el[0].text.strip() if name_el else ""
    job_name  = job_el[0].text.strip()  if job_el  else ""
    salary    = salary_el[0].text.strip() if salary_el else ""
    location  = loc_el[0].text.strip()  if loc_el  else ""

    if not comp_name:
        return None

    industry = scale = stage = ""
    for el in compinfo_els:
        t = el.text.strip()
        if not t:
            continue
        if not industry:
            industry = t
        elif not scale:
            scale = t
        else:
            stage = t

    contact_person, contact_info = _extract_contact_from_item(item)

    return CompanyInfo(
        platform="智联招聘", name=comp_name,
        industry=industry or "—", scale=scale or "—",
        stage=stage or "—", description="",
        location=location, hot_jobs=job_name, salary=salary,
        contact_person=contact_person,
        contact_info=contact_info,
    )


def parse_51job_item(item) -> CompanyInfo | None:
    """解析前程无忧单条职位卡片"""
    sensor_raw = ""
    wrapper = item.find_elements(By.CSS_SELECTOR, "[sensorsdata]")
    if wrapper:
        sensor_raw = wrapper[0].get_attribute("sensorsdata") or ""

    job_name = salary = location = ""
    comp_name = industry = scale = stage = ""

    if sensor_raw:
        try:
            sd = json.loads(sensor_raw)
            job_name = sd.get("jobTitle", "")
            salary   = sd.get("jobSalary", "")
            location = sd.get("jobArea", "")
        except (json.JSONDecodeError, TypeError):
            pass

    text = item.text
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not job_name and lines:
        job_name = lines[0]
    if not salary and len(lines) > 1:
        salary = lines[1]

    for line in lines:
        if "人" in line and not scale:
            scale = line
        elif any(k in line for k in ("民营", "外资", "合资", "国企",
                                      "上市", "私营", "股份")):
            if not stage:
                stage = line

    comp_els = item.find_elements(By.CSS_SELECTOR,
        ".companyinfo-text, .companyinfo__name, [class*=company] a, .company-name")
    if comp_els:
        comp_name = comp_els[0].text.strip()
    if not comp_name:
        for line in lines:
            if any(k in line for k in ("公司", "有限", "集团", "科技", "股份", "工业")):
                comp_name = line
                break

    if not comp_name and not job_name:
        return None

    contact_person, contact_info = _extract_contact_from_item(item)

    return CompanyInfo(
        platform="前程无忧", name=comp_name or "—",
        industry=industry or "—", scale=scale or "—",
        stage=stage or "—", description="",
        location=location, hot_jobs=job_name, salary=salary,
        contact_person=contact_person,
        contact_info=contact_info,
    )


def parse_boss_item(item) -> CompanyInfo | None:
    """解析 Boss直聘单条职位卡片"""
    name_els = item.find_elements(By.CSS_SELECTOR, ".company-name, .name, [class*=company]")
    job_els  = item.find_elements(By.CSS_SELECTOR, ".job-name, .job-title, [class*=job-name]")
    sal_els  = item.find_elements(By.CSS_SELECTOR, ".salary, .job-info .salary, [class*=salary]")
    area_els = item.find_elements(By.CSS_SELECTOR, ".job-area, .job-info .area, [class*=area]")

    comp = name_els[0].text.strip() if name_els else ""
    if not comp:
        return None

    contact_person, contact_info = _extract_contact_from_item(item)

    return CompanyInfo(
        platform="Boss直聘", name=comp,
        industry="—", scale="—", stage="—",
        description="",
        location=area_els[0].text.strip() if area_els else "—",
        hot_jobs=job_els[0].text.strip() if job_els else "—",
        salary=sal_els[0].text.strip() if sal_els else "—",
        contact_person=contact_person,
        contact_info=contact_info,
    )


def _first_text(item, *selectors: str) -> str:
    for sel in selectors:
        for el in item.find_elements(By.CSS_SELECTOR, sel):
            text = el.text.strip()
            if text:
                return text
    return ""


LAGOU_SCALE_RE = re.compile(
    r"(?:少于\s*)?\d+\s*[-~～至]\s*\d+\s*人|\d+\s*人以上|10000\s*人以上|不公开",
    re.I,
)


def _extract_scale(text: str) -> str:
    if not text:
        return "—"
    match = LAGOU_SCALE_RE.search(text.replace(" ", ""))
    if match:
        return match.group(0)
    match = LAGOU_SCALE_RE.search(text)
    return match.group(0) if match else "—"


def _split_lagou_meta(text: str) -> tuple[str, str]:
    """解析「行业 / 融资阶段 / 规模」→ 只取行业和规模。"""
    if not text:
        return "—", "—"
    parts = [p.strip() for p in re.split(r"\s*[·/|]\s*", text) if p.strip()]
    if not parts:
        return "—", "—"
    industry = parts[0]
    scale = "—"
    for part in reversed(parts):
        found = _extract_scale(part)
        if found != "—":
            scale = found
            break
    if scale == "—" and len(parts) >= 2:
        scale = _extract_scale(text)
    return industry, scale


def _looks_like_company_name(text: str, company_name: str) -> bool:
    if not text or not company_name:
        return False
    a = re.sub(r"\s+", "", text)
    b = re.sub(r"\s+", "", company_name)
    return a == b or a in b or b in a


def _parse_lagou_meta(item, company_name: str = "") -> tuple[str, str]:
    """
    解析行业、规模。
    行业在 .industry_field；勿从 .company / .company_name 取文本。
    """
    industry = _first_text(
        item,
        ".company_others .industry_field",
        ".industry_field",
        ".list_item_bot .li_b_l .industry",
    )
    if _looks_like_company_name(industry, company_name):
        industry = ""

    scale = _first_text(
        item,
        ".company_others .scale",
        ".list_item_bot .li_b_l .scale",
    )
    if scale == "—" or not scale:
        scale = ""

    for el in item.find_elements(By.CSS_SELECTOR, ".company_others"):
        raw = el.text.strip()
        if company_name and raw.startswith(company_name):
            raw = raw[len(company_name):].strip()
        if raw:
            ind, sc = _split_lagou_meta(raw)
            if not industry and not _looks_like_company_name(ind, company_name):
                industry = ind
            if not scale and sc != "—":
                scale = sc
        for span in el.find_elements(By.CSS_SELECTOR, "span.industry_field, span.industry"):
            text = span.text.strip()
            if text and not _looks_like_company_name(text, company_name):
                industry = text
                break
        if not scale:
            for span in el.find_elements(By.CSS_SELECTOR, "span"):
                text = span.text.strip()
                found = _extract_scale(text)
                if found != "—":
                    scale = found
                    break

    for el in item.find_elements(By.CSS_SELECTOR, ".list_item_bot .li_b_l"):
        raw = el.text.strip()
        if raw and ("/" in raw or "·" in raw or "|" in raw):
            ind, sc = _split_lagou_meta(raw)
            if not industry and not _looks_like_company_name(ind, company_name):
                industry = ind
            if not scale and sc != "—":
                scale = sc

    if industry and re.search(r"[/|·]", industry):
        ind, sc = _split_lagou_meta(industry)
        industry = ind if not _looks_like_company_name(ind, company_name) else ""
        if not scale and sc != "—":
            scale = sc

    if _looks_like_company_name(industry, company_name):
        industry = ""

    scale = scale or _extract_scale(item.text or "")
    return industry or "—", scale if scale != "—" else "—"


def parse_lagou_item(item) -> CompanyInfo | None:
    """解析拉勾网单条职位卡片（公司维度：名称、行业、规模、地点）。"""
    comp = _first_text(
        item,
        ".company_name a",
        ".company_name",
        ".company-name a",
        ".company-name",
        ".company-name__2-SjF",
    )
    location = _first_text(item, ".add", ".position-area")
    industry, scale = _parse_lagou_meta(item, company_name=comp)

    if not comp:
        return None

    return CompanyInfo(
        platform="拉勾网",
        name=comp,
        industry=industry,
        scale=scale,
        stage="",
        description="",
        location=location or "—",
        hot_jobs="",
        salary="",
        contact_person="",
        contact_info="",
    )


def parse_liepin_item(item) -> CompanyInfo | None:
    """解析猎聘单条职位卡片"""
    comp = _first_text(
        item,
        "[class*='company-name'] a",
        "[class*='company-name']",
        ".company-name a",
        ".company-name",
        ".comp-name a",
        ".comp-name",
        ".job-card .company",
        ".sojob-item .company-name",
    )
    job = _first_text(
        item,
        "[class*='job-title'] a",
        "[class*='job-title']",
        ".job-title-box .ellipsis-1",
        ".job-name a",
        ".job-name",
        ".sojob-item .job-name",
    )
    salary = _first_text(
        item,
        "[class*='job-salary']",
        "[class*='salary']",
        ".job-finance-info .tag",
        ".sojob-item .salary",
        ".job-card .salary",
    )
    location = _first_text(
        item,
        "[class*='job-dq']",
        "[class*='job-area']",
        ".job-area",
        ".job-detail .dq",
    )

    if not comp:
        return None

    industry = scale = ""
    for el in item.find_elements(
        By.CSS_SELECTOR,
        ".company-info span, [class*='company-info'] span, "
        "[class*='company-tags'] span, .sojob-item .industry",
    ):
        t = el.text.strip()
        if not t:
            continue
        if not industry:
            industry = t
        elif not scale:
            scale = t

    return CompanyInfo(
        platform="猎聘", name=comp,
        industry=industry or "—", scale=scale or "—",
        stage="—", description="",
        location=location or "—",
        hot_jobs=job or "—",
        salary=salary or "—",
        contact_person="",
        contact_info="",
    )


# ──────────────────────────────────────────────
# 平台配置表（供 engine 使用）
# ──────────────────────────────────────────────

PLATFORM_CONFIG = {
    "zhilian": {
        "url_tpl": "https://sou.zhaopin.com/?kw={kw}&jl={city}&p={page}",
        "item_css": ".joblist-box__item, .positionlist-box li, "
                    "[class*=joblist] [class*=item], .job-card-item",
        "next_css": ".pagination__next:not(.disabled), button.btn-pager-next:not([disabled]), "
                    "li.next:not(.disabled), a[class*=next]:not(.disabled)",
        "empty_css": ".joblist-empty, .search-no-result, .no-result-panel",
        "parse_fn": parse_zhilian_item,
        "method": "browser",
        "page_delay": (3, 5),
    },
    "51job": {
        "url_tpl": "https://we.51job.com/pc/search?keyword={kw}"
                   "&searchType=2&sortType=0&jobArea={city}&pageNum={page}",
        "item_css": ".joblist-item, .job-list-item, "
                    "[class*=joblist] [class*=item]",
        "next_css": ".el-pagination .btn-next:not([disabled]), button.btn-next:not([disabled]), "
                    "li.next:not(.disabled), .pagination .next:not(.disabled)",
        "empty_css": ".no-result, .empty-data, .el-empty",
        "parse_fn": parse_51job_item,
        "method": "browser",
        "page_delay": (3, 5),
    },
    "boss": {
        "url_tpl": "https://www.zhipin.com/web/geek/job?query={kw}&city={city}&page={page}",
        "item_css": ".job-card-wrapper, .job-card-body, "
                    ".search-job-result .job-list-box li, [class*=job-card]",
        "next_css": ".options-pages a:last-child:not(.disabled), .pagination a.next:not(.disabled), "
                    "button[aria-label='下一页']:not([disabled]), .page-next:not(.disabled)",
        "empty_css": ".job-empty, .empty-page, .search-empty",
        "parse_fn": parse_boss_item,
        "method": "browser",
        "requires_login": True,
        "page_delay": (4, 7),
    },
    "lagou": {
        "url_tpl": "https://www.lagou.com/wn/search/?kd={kw}&pn={page}",
        "item_css": ".con_list_item",
        "next_css": ".pager_next, span[action='next'], "
                    ".pager_container span:last-child, "
                    ".lg-page-item.next:not(.disabled), "
                    "li.next:not(.disabled)",
        "empty_css": ".search-no-result, .empty-position",
        "parse_fn": parse_lagou_item,
        "dedupe_by": "name",
        "captcha_title_keywords": ["访问验证"],
        "captcha_body_keywords": ["验证失败", "请进行验证"],
        "captcha_css": "iframe[src*='verify'], iframe[src*='captcha'], "
                       ".geetest_panel, #tcaptcha, [class*='verify-wrap'], [class*='access-verify']",
        "method": "browser",
        "page_delay": (8, 14),
    },
    "liepin": {
        "url_tpl": "https://www.liepin.com/zhaopin/?key={kw}&curPage={page}",
        "item_css": ".job-list-box > div, .job-list-box [class*='job-card'], "
                    "[class*='job-card-pc'], .job-card-pc-container, "
                    ".job-list-item, .sojob-list li",
        "next_css": ".ant-pagination-next:not(.ant-pagination-disabled) button, "
                    "li.next:not(.disabled), button[aria-label='下一页']:not([disabled]), "
                    ".pagination__next:not(.disabled)",
        "empty_css": ".ant-empty, .no-data, .search-empty",
        "parse_fn": parse_liepin_item,
        "captcha_title_keywords": ["安全中心"],
        "captcha_body_keywords": ["安全验证", "访问受限"],
        "method": "browser",
        "page_delay": (5, 8),
    },
}
