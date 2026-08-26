#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
各平台的页面解析函数（与爬虫引擎解耦，便于单独更新选择器）
"""

import json

from selenium.webdriver.common.by import By

from .models import CompanyInfo


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

    return CompanyInfo(
        platform="智联招聘", name=comp_name,
        industry=industry or "—", scale=scale or "—",
        stage=stage or "—", description="",
        location=location, hot_jobs=job_name, salary=salary,
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

    return CompanyInfo(
        platform="前程无忧", name=comp_name or "—",
        industry=industry or "—", scale=scale or "—",
        stage=stage or "—", description="",
        location=location, hot_jobs=job_name, salary=salary,
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

    return CompanyInfo(
        platform="Boss直聘", name=comp,
        industry="—", scale="—", stage="—",
        description="",
        location=area_els[0].text.strip() if area_els else "—",
        hot_jobs=job_els[0].text.strip() if job_els else "—",
        salary=sal_els[0].text.strip() if sal_els else "—",
    )


def parse_lagou_item(item) -> CompanyInfo | None:
    """解析拉勾网单条职位卡片"""
    name_els = item.find_elements(
        By.CSS_SELECTOR,
        ".company-name__2-SjF, .company-name, [class*=companyName], [class*=company-name], .con_list_item .company_name",
    )
    job_els = item.find_elements(
        By.CSS_SELECTOR,
        ".position-name__2Kw3s, .position-name, [class*=positionName], .con_list_item .job-name",
    )
    sal_els = item.find_elements(
        By.CSS_SELECTOR,
        ".salary__13530, .money, [class*=salary], .con_list_item .salary",
    )
    info_els = item.find_elements(
        By.CSS_SELECTOR,
        ".industry, [class*=industry], .con_list_item .industry",
    )

    comp = name_els[0].text.strip() if name_els else ""
    if not comp:
        return None

    return CompanyInfo(
        platform="拉勾网", name=comp,
        industry=info_els[0].text.strip() if info_els else "—",
        scale="—", stage="—", description="", location="—",
        hot_jobs=job_els[0].text.strip() if job_els else "—",
        salary=sal_els[0].text.strip() if sal_els else "—",
    )


def parse_liepin_item(item) -> CompanyInfo | None:
    """解析猎聘单条职位卡片"""
    name_els = item.find_elements(By.CSS_SELECTOR, ".company-name, [class*=companyName], .job-card .company, .sojob-item .company-name")
    job_els  = item.find_elements(By.CSS_SELECTOR, ".job-title-box .ellipsis-1, [class*=jobTitle], .sojob-item .job-name, .job-card .job-name")
    sal_els  = item.find_elements(By.CSS_SELECTOR, ".job-finance-info .tag, [class*=salary], .sojob-item .salary, .job-card .salary")
    info_els = item.find_elements(By.CSS_SELECTOR, ".company-info span, [class*=companyInfo], .sojob-item .industry")

    comp = name_els[0].text.strip() if name_els else ""
    if not comp:
        return None

    industry = ""
    scale = ""
    for el in info_els:
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
        stage="—", description="", location="—",
        hot_jobs=job_els[0].text.strip() if job_els else "—",
        salary=sal_els[0].text.strip() if sal_els else "—",
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
        "item_css": ".item__10RTO, [class*=ItemList] > div, "
                    "[class*=job-list] li, .position-list .item, "
                    ".position-item, [class*=position-item], [class*=job-item], "
                    ".con_list_item, .default-list>.item",
        "next_css": ".lg-pagination-next:not(.lg-pagination-disabled), "
                    ".pager_next:not(.pager_next_disabled), "
                    ".pager_next, button[aria-label*='下一页']:not([disabled])",
        "empty_css": ".search-no-result, .empty-position",
        "parse_fn": parse_lagou_item,
        "captcha_title_keywords": ["访问验证"],
        "captcha_body_keywords": ["验证失败", "请进行验证", "请刷新"],
        "captcha_css": "iframe[src*='verify'], iframe[src*='captcha'], "
                       ".geetest_panel, #tcaptcha, [class*='verify-wrap'], [class*='access-verify']",
        "method": "browser",
        "page_delay": (5, 8),
    },
    "liepin": {
        "url_tpl": "https://www.liepin.com/zhaopin/?key={kw}&curPage={page}",
        "item_css": ".job-card-pc-container, [class*=job-card], [class*=JobCard], "
                    ".job-list-item, .job-card, .sojob-list li, .job-list li",
        "next_css": ".ant-pagination-next:not(.ant-pagination-disabled) button, "
                    "li.next:not(.disabled), button[aria-label='下一页']:not([disabled]), "
                    ".pagination__next:not(.disabled)",
        "empty_css": ".ant-empty, .no-data",
        "parse_fn": parse_liepin_item,
        "captcha_title_keywords": ["安全中心"],
        "captcha_body_keywords": ["安全验证", "访问受限"],
        "method": "browser",
        "page_delay": (5, 8),
    },
}