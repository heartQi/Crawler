#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局常量与配置
"""

import os

# ──────────────────────────────────────────────
# 爬取状态常量
# ──────────────────────────────────────────────
CRAWL_OK      = "online"      # 在线爬取成功
CRAWL_BLOCKED = "blocked"     # 被反爬拦截
MAX_PAGES     = 50            # 安全翻页上限

# ──────────────────────────────────────────────
# 文件路径
# ──────────────────────────────────────────────
COOKIE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".cookies.json",
)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(PROJECT_DIR, ".credentials.json")
BROWSER_PROFILE_DIR = os.path.join(PROJECT_DIR, ".browser_profile")
MANUAL_BROWSER_PROFILE_DIR = os.path.join(PROJECT_DIR, ".manual_browser")
REMOTE_DEBUG_PORT = 9222
# 强验证站点：用普通 Chrome 手动过验证后再附着，避免 WebDriver 启动被识别
REMOTE_CHROME_PLATFORMS = frozenset({"lagou", "liepin"})

# Selenium 可见浏览器参数
BROWSER_HEADLESS = False
PAGE_LOAD_TIMEOUT = 30
ELEMENT_WAIT_TIMEOUT = 15
LOGIN_WAIT_TIMEOUT = 300
HUMAN_DELAY_RANGE = (0.6, 1.4)

# ── 第一步：零成本反限流节奏（通用） ──
CRAWL_REQUEST_DELAY = (3.0, 8.0)         # 模拟真人：单次操作随机 3~8 秒
CRAWL_COOLDOWN_EVERY = 50                # 每 N 次请求插入冷却
CRAWL_COOLDOWN_DURATION = (15.0, 30.0)   # 冷却时长（秒）
CRAWL_BACKOFF_BASE = 8.0                 # 429/WAF 退避基数
CRAWL_BACKOFF_FACTOR = 2.0
CRAWL_BACKOFF_MAX = 180.0

# 拉勾 Ajax 专用（接口更敏感，间隔长于通用节奏）
LAGOU_AJAX_INTERVAL = (45.0, 75.0)       # 两次接口请求之间的随机等待（秒）
LAGOU_AJAX_PAGE_EXTRA = (8.0, 15.0)        # 每往后翻一页额外增加的随机等待
LAGOU_AJAX_LONG_PAUSE_EVERY = 2            # 每 N 次 Ajax 长休息一次
LAGOU_AJAX_LONG_PAUSE = (90.0, 150.0)     # 长休息时长（秒）
LAGOU_AJAX_HIGH_PAGE_EXTRA = (50.0, 80.0)  # 第 4 页起浏览器停留额外等待
LAGOU_BACKOFF_BASE = 60.0                  # 限流退避基数（秒）
LAGOU_BACKOFF_FACTOR = 2.0
LAGOU_BACKOFF_JITTER = (20.0, 45.0)
LAGOU_AJAX_MAX_RETRIES = 2                 # 单页限流后最多再试次数（避免猛砸）

# ──────────────────────────────────────────────
# User-Agent 池
# ──────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

# ──────────────────────────────────────────────
# 城市映射：显示名 → { 平台: 平台城市代码 }
# ──────────────────────────────────────────────
CITIES = {
    "北京": {"zhilian": "530",  "51job": "010000", "boss": "101010100", "liepin": "010"},
    "上海": {"zhilian": "538",  "51job": "020000", "boss": "101020100", "liepin": "020"},
    "广州": {"zhilian": "763",  "51job": "030200", "boss": "101280100", "liepin": "050020"},
    "深圳": {"zhilian": "765",  "51job": "040000", "boss": "101280600", "liepin": "050090"},
    "杭州": {"zhilian": "653",  "51job": "080200", "boss": "101210100", "liepin": "070020"},
    "成都": {"zhilian": "801",  "51job": "090200", "boss": "101270100", "liepin": "090020"},
    "南京": {"zhilian": "635",  "51job": "070200", "boss": "101190100", "liepin": "060020"},
    "武汉": {"zhilian": "736",  "51job": "180200", "boss": "101200100", "liepin": "170020"},
    "西安": {"zhilian": "854",  "51job": "200200", "boss": "101110100", "liepin": "200020"},
    "重庆": {"zhilian": "551",  "51job": "060000", "boss": "101040100", "liepin": "040"},
    "苏州": {"zhilian": "639",  "51job": "070300", "boss": "101190400", "liepin": "060080"},
    "天津": {"zhilian": "531",  "51job": "050000", "boss": "101030100", "liepin": "030"},
    "长沙": {"zhilian": "749",  "51job": "190200", "boss": "101250100", "liepin": "180020"},
    "郑州": {"zhilian": "665",  "51job": "170200", "boss": "101180100", "liepin": "140020"},
    "青岛": {"zhilian": "682",  "51job": "120300", "boss": "101120200", "liepin": "120020"},
    "大连": {"zhilian": "599",  "51job": "230300", "boss": "101070200", "liepin": "210040"},
    "厦门": {"zhilian": "682",  "51job": "110200", "boss": "101230100", "liepin": "110020"},
    "合肥": {"zhilian": "702",  "51job": "150200", "boss": "101220100", "liepin": "150020"},
    "全国": {"zhilian": "0",    "51job": "",       "boss": "100010000", "liepin": "410"},
}

# ──────────────────────────────────────────────
# 平台定义
# ──────────────────────────────────────────────
PLATFORMS = {
    "boss": {
        "name": "Boss直聘", "color": "#00C4B4", "method": "browser",
        "domain": "https://www.zhipin.com",
        "requires_login": True,
        "note": "可见浏览器登录后逐页采集",
    },
    "zhilian": {
        "name": "智联招聘", "color": "#1A73E8", "method": "browser",
        "domain": "",
        "requires_login": False,
        "note": "可见浏览器逐页采集",
    },
    "51job": {
        "name": "前程无忧", "color": "#FF6600", "method": "browser",
        "domain": "",
        "requires_login": False,
        "note": "可见浏览器逐页采集",
    },
    "lagou": {
        "name": "拉勾网",   "color": "#14558E", "method": "browser",
        "domain": "https://www.lagou.com",
        "requires_login": False,
        "note": "可见浏览器逐页采集",
    },
    "liepin": {
        "name": "猎聘",     "color": "#2F5BEA", "method": "browser",
        "domain": "https://www.liepin.com",
        "requires_login": False,
        "note": "可见浏览器逐页采集",
    },
}

# ──────────────────────────────────────────────
# GUI 颜色主题
# ─────────────────────────────────────────────────
BG         = "#F5F7FA"
CARD_BG    = "#FFFFFF"
PRIMARY    = "#4A90D9"
TEXT_DARK  = "#2C3E50"
TEXT_LIGHT = "#7F8C8D"
ACCENT     = "#27AE60"
DANGER     = "#E74C3C"