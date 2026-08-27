#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爬虫请求节奏 — 随机延迟、周期冷却、指数退避（零成本反限流基础层）。"""

from __future__ import annotations

import random
import time
from typing import Callable, Optional

from .config import (
    CRAWL_BACKOFF_BASE,
    CRAWL_BACKOFF_FACTOR,
    CRAWL_BACKOFF_MAX,
    CRAWL_COOLDOWN_DURATION,
    CRAWL_COOLDOWN_EVERY,
    CRAWL_REQUEST_DELAY,
)

_log: Optional[Callable[[str], None]] = None


class RequestPacer:
    """全局请求计数 + 随机间隔 + 周期性冷却。"""

    def __init__(self) -> None:
        self.total_requests = 0
        self.rate_limit_hits = 0

    def reset(self) -> None:
        self.total_requests = 0
        self.rate_limit_hits = 0

    def wait_before_request(
        self,
        delay_range: tuple[float, float] | None = None,
        log: Callable[[str], None] | None = None,
        label: str = "",
        count_request: bool = True,
    ) -> None:
        """随机延迟；count_request=True 时计入总请求数并可能触发周期冷却。"""
        if count_request:
            self.record_request()
            self.maybe_periodic_cooldown(log=log)
        emit = log or _log
        lo, hi = delay_range or CRAWL_REQUEST_DELAY
        delay = random.uniform(lo, hi)
        if emit and label:
            emit(f"[节奏] {label}，等待 {delay:.1f} 秒...")
        time.sleep(delay)

    def record_request(self) -> int:
        self.total_requests += 1
        return self.total_requests

    def maybe_periodic_cooldown(
        self,
        log: Callable[[str], None] | None = None,
    ) -> bool:
        """每 N 次请求冷却一次，返回是否执行了冷却。"""
        emit = log or _log
        if (
            CRAWL_COOLDOWN_EVERY <= 0
            or self.total_requests < 1
            or self.total_requests % CRAWL_COOLDOWN_EVERY != 0
        ):
            return False
        cooldown = random.uniform(*CRAWL_COOLDOWN_DURATION)
        if emit:
            emit(
                f"[节奏] 已完成 {self.total_requests} 次请求，"
                f"冷却 {cooldown:.0f} 秒..."
            )
        time.sleep(cooldown)
        return True

    def backoff_wait(self, attempt: int, log: Callable[[str], None] | None = None,
                     page: int = 0) -> float:
        """指数退避（仅计算并 sleep，返回等待秒数）。"""
        self.rate_limit_hits += 1
        wait = min(
            CRAWL_BACKOFF_BASE * (CRAWL_BACKOFF_FACTOR ** attempt),
            CRAWL_BACKOFF_MAX,
        )
        wait += random.uniform(2.0, 8.0)
        emit = log or _log
        if emit:
            hint = f"第 {page} 页" if page else "请求"
            emit(
                f"[节奏] {hint}被限流，指数退避 {wait:.0f} 秒 "
                f"(重试 {attempt + 2})..."
            )
        time.sleep(wait)
        return wait


# 拉勾等模块共用的单例
_global_pacer = RequestPacer()


def get_pacer() -> RequestPacer:
    return _global_pacer


def reset_pacer() -> None:
    _global_pacer.reset()
