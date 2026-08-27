#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉勾网浏览器内翻页辅助。"""

from __future__ import annotations

import re
import time
from typing import Callable, Iterable, List, Tuple

from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

LAGOU_LIST_ROOT_CSS = (
    "#s_position_list, .item_con, [class*='job-list'], "
    "[class*='position-list'], [class*='search-job-list']"
)
LAGOU_LIST_ITEM_CSS = (
    "li.con_list_item, .con_list_item, "
    "[class*='position-item'], [class*='job-card'], "
    "[class*='JobCard'], [class*='job_item'], "
    "[class*='position-card']"
)

_READ_PAGE_JS = """
let root = document.querySelector('.pager_container');
if (root) {
  const cur = root.querySelector('.pager_current, span.pager_current');
  if (cur) {
    const val = (cur.getAttribute('action') || cur.textContent || '').trim();
    if (/^\\d+$/.test(val)) return parseInt(val, 10);
  }
  const spans = root.querySelectorAll('span.page_no, span[action]');
  for (const s of spans) {
    const action = (s.getAttribute('action') || '').trim();
    if (!/^\\d+$/.test(action)) continue;
    const cls = (s.className || '').toLowerCase();
    if (cls.includes('current') || cls.includes('active')) return parseInt(action, 10);
  }
}
const ant = document.querySelector('.ant-pagination, [class*="Pagination"], [class*="pagination"]');
if (ant) {
  const active = ant.querySelector(
    '.ant-pagination-item-active, [class*="active"][class*="page"], li.active, .current'
  );
  if (active) {
    const t = (active.textContent || active.innerText || '').trim();
    if (/^\\d+$/.test(t)) return parseInt(t, 10);
  }
}
return 0;
"""

LAGOU_PAGER_CSS = (
    ".pager_container",
    ".ant-pagination",
    "[class*='Pagination']",
    "[class*='pagination']",
    ".lg-page",
    "[class*='pager']",
)


def scroll_lagou_list_to_top(driver) -> None:
    try:
        roots = driver.find_elements(By.CSS_SELECTOR, LAGOU_LIST_ROOT_CSS)
        if roots:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'start'});", roots[0],
            )
        time.sleep(0.6)
    except WebDriverException:
        pass


def find_current_page_lagou_items(driver, limit: int = 20) -> List[WebElement]:
    scroll_lagou_list_to_top(driver)
    items: List[WebElement] = []
    try:
        roots = driver.find_elements(By.CSS_SELECTOR, LAGOU_LIST_ROOT_CSS)
        candidates = (
            roots[0].find_elements(By.CSS_SELECTOR, LAGOU_LIST_ITEM_CSS)
            if roots
            else driver.find_elements(By.CSS_SELECTOR, LAGOU_LIST_ITEM_CSS)
        )
        for el in candidates:
            try:
                if not el.is_displayed():
                    continue
                size = el.size or {}
                if size.get("height", 0) <= 0:
                    continue
                items.append(el)
                if len(items) >= limit:
                    break
            except StaleElementReferenceException:
                continue
    except WebDriverException:
        pass
    return items


def _item_fingerprint(item) -> str:
    try:
        pid = (item.get_attribute("data-positionid") or "").strip()
        if pid:
            return f"id:{pid}"
        lgid = (item.get_attribute("data-lgid") or "").strip()
        if lgid:
            return f"lg:{lgid}"
        links = item.find_elements(By.CSS_SELECTOR, "a.position_link")
        if links:
            href = (links[0].get_attribute("href") or "").strip()
            if href and href not in ("#", "javascript:;"):
                return href
            lg = (links[0].get_attribute("data-lgid") or "").strip()
            if lg:
                return f"lg:{lg}"
            title = links[0].text.strip()
            if title:
                return f"job:{title}"
        comp = item.find_elements(By.CSS_SELECTOR, ".company_name, .company-name")
        job = item.find_elements(By.CSS_SELECTOR, "a.position_link, .p_top a")
        if comp and job:
            return f"{comp[0].text.strip()}|{job[0].text.strip()}"
    except StaleElementReferenceException:
        pass
    return ""


def lagou_position_signature(items: Iterable) -> tuple:
    keys = []
    for item in items:
        fp = _item_fingerprint(item)
        if fp:
            keys.append(fp)
    return tuple(keys)


def lagou_has_pager(driver) -> bool:
    for sel in LAGOU_PAGER_CSS:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed():
                    return True
        except WebDriverException:
            continue
    return False


def read_lagou_total_pages(driver) -> int:
    selectors = (".totalNum", "span.totalNum", "[class*='totalNum']")
    for sel in selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                text = (el.text or "").strip()
                if text.isdigit():
                    return int(text)
        except WebDriverException:
            continue
    return 0


def read_lagou_current_page(driver) -> int:
    try:
        value = driver.execute_script(_READ_PAGE_JS)
        if isinstance(value, int) and value > 0:
            return value
    except WebDriverException:
        pass

    try:
        pagers = driver.find_elements(By.CSS_SELECTOR, ".pager_container")
        if not pagers:
            return 0
        pager = pagers[0]
        for el in pager.find_elements(By.CSS_SELECTOR, "span"):
            cls = el.get_attribute("class") or ""
            if "pager_current" in cls:
                val = (el.get_attribute("action") or el.text or "").strip()
                if val.isdigit():
                    return int(val)
        html = pager.get_attribute("innerHTML") or ""
        m = re.search(r'pager_current[^>]*action=["\']?(\d+)', html)
        if m:
            return int(m.group(1))
    except WebDriverException:
        pass
    return 0


def sync_lagou_page_from_browser(driver, expected_min: int = 0) -> int:
    """读取浏览器分页条当前页码。"""
    page = read_lagou_current_page(driver)
    if page > 0:
        return page
    return expected_min


def _is_disabled(el) -> bool:
    cls = (el.get_attribute("class") or "").lower()
    return "disabled" in cls or (el.get_attribute("aria-disabled") or "").lower() in ("true", "disabled")


def _click_element(driver, el) -> None:
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});", el,
    )
    time.sleep(0.5)
    try:
        el.click()
    except WebDriverException:
        driver.execute_script("arguments[0].click();", el)


def _find_lagou_next_button(driver):
    strategies: Tuple[Tuple[str, str], ...] = (
        (By.XPATH, "//div[contains(@class,'pager_container')]//span[@action='next']"),
        (By.CSS_SELECTOR, ".pager_container .pager_next"),
        (By.CSS_SELECTOR, ".pager_next"),
        (By.CSS_SELECTOR, ".ant-pagination-next:not(.ant-pagination-disabled)"),
        (By.CSS_SELECTOR, "[class*='pagination'] .next:not(.disabled)"),
        (By.CSS_SELECTOR, ".lg-page-item.next:not(.disabled)"),
        (By.XPATH, "//button[contains(@aria-label,'下一页') and not(@disabled)]"),
        (By.XPATH, "//li[contains(@class,'next') and not(contains(@class,'disabled'))]"),
    )
    for by, selector in strategies:
        try:
            for el in driver.find_elements(by, selector):
                if not el.is_displayed() or _is_disabled(el):
                    continue
                if "pager_next_disabled" in (el.get_attribute("class") or ""):
                    continue
                return el
        except WebDriverException:
            continue
    return None


def _find_lagou_page_button(driver, page_num: int):
    strategies: Tuple[Tuple[str, str], ...] = (
        (
            By.XPATH,
            f"//div[contains(@class,'pager_container')]//span["
            f"(@class='page_no' or contains(@class,'page_no')) and "
            f"(@action='{page_num}' or normalize-space(text())='{page_num}')]",
        ),
        (
            By.XPATH,
            f"//div[contains(@class,'pager_container')]//span["
            f"@action='{page_num}' or normalize-space(text())='{page_num}']",
        ),
        (
            By.XPATH,
            f"//li[contains(@class,'ant-pagination-item') and "
            f"normalize-space(text())='{page_num}']",
        ),
        (
            By.XPATH,
            f"//*[contains(@class,'pagination') or contains(@class,'pager')]"
            f"//*[normalize-space(text())='{page_num}']",
        ),
    )
    for by, selector in strategies:
        try:
            for el in driver.find_elements(by, selector):
                action = (el.get_attribute("action") or "").strip()
                if action in ("next", "previous"):
                    continue
                if not el.is_displayed() or _is_disabled(el):
                    continue
                return el
        except WebDriverException:
            continue
    return None


def _page_content_changed(driver, old_signature: tuple) -> bool:
    items = find_current_page_lagou_items(driver)
    new_sig = lagou_position_signature(items)
    return bool(new_sig) and new_sig != old_signature


def _wait_page_turn(
    driver,
    from_page: int,
    target_page: int,
    old_signature: tuple,
    log: Callable[[str], None],
) -> int:
    for wait_round in range(15):
        time.sleep(1.2)
        scroll_lagou_list_to_top(driver)

        pager_page = read_lagou_current_page(driver)
        if pager_page > from_page:
            log(f"[拉勾网] 分页已到第 {pager_page} 页")
            return pager_page

        if _page_content_changed(driver, old_signature):
            detected = read_lagou_current_page(driver) or target_page
            log(f"[拉勾网] 第 {detected} 页列表已更新")
            return detected

        if wait_round == 5:
            log(f"[拉勾网] 等待第 {target_page} 页加载...")

    pager_page = read_lagou_current_page(driver)
    if pager_page > from_page:
        return pager_page
    if _page_content_changed(driver, old_signature):
        return read_lagou_current_page(driver) or target_page
    return from_page


def go_next_lagou_page(
    driver,
    current_page: int,
    old_signature: tuple,
    log: Callable[[str], None] = print,
) -> int:
    """翻到下一页，优先点击目标页码。"""
    next_page = current_page + 1

    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    except WebDriverException:
        pass
    time.sleep(0.8)

    page_btn = _find_lagou_page_button(driver, next_page)
    clicked = False
    if page_btn is not None:
        log(f"[拉勾网] 点击页码 {next_page}...")
        clicked = True
        try:
            _click_element(driver, page_btn)
        except WebDriverException:
            page_btn = None
            clicked = False

    if page_btn is not None:
        turned = _wait_page_turn(driver, current_page, next_page, old_signature, log)
        if turned > current_page:
            return turned

    next_btn = _find_lagou_next_button(driver)
    if next_btn is not None and not clicked:
        log("[拉勾网] 点击下一页...")
        clicked = True
        try:
            _click_element(driver, next_btn)
        except StaleElementReferenceException:
            next_btn = _find_lagou_next_button(driver)
            if next_btn is not None:
                _click_element(driver, next_btn)
            else:
                clicked = False
        if clicked:
            turned = _wait_page_turn(driver, current_page, next_page, old_signature, log)
            if turned > current_page:
                return turned

    synced = read_lagou_current_page(driver)
    if synced > current_page:
        log(f"[拉勾网] 浏览器已在第 {synced} 页")
        return synced

    if clicked and find_current_page_lagou_items(driver):
        log(f"[拉勾网] 第 {next_page} 页已打开，继续采集")
        return next_page

    log(f"[拉勾网] 第 {next_page} 页未能确认加载，停止翻页")
    return current_page
