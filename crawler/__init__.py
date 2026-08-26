#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
招聘平台公司信息爬虫工具
- 支持 Boss直聘、智联招聘、前程无忧、拉勾、猎聘 等平台
- tkinter GUI 弹窗展示爬取结果
- 支持关键词搜索、结果导出
"""

# 注意：engine/gui 依赖 selenium，由 main.py 运行时按需导入
from .config import (
    PLATFORMS, CITIES, USER_AGENTS, COOKIE_FILE,
    CRAWL_OK, CRAWL_BLOCKED, MAX_PAGES,
)
from .models import CompanyInfo, CrawlResult
from .cookie import CookieManager