#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型定义
"""

from dataclasses import dataclass, asdict
from typing import List


@dataclass
class CompanyInfo:
    """公司信息"""
    platform: str       # 来源平台
    name: str           # 公司名称
    industry: str       # 行业
    scale: str          # 规模
    stage: str          # 融资阶段
    description: str    # 简介
    location: str       # 地址
    hot_jobs: str       # 热招岗位
    salary: str         # 薪资范围

    def to_list(self):
        return [self.platform, self.name, self.industry, self.scale,
                self.stage, self.description, self.location,
                self.hot_jobs, self.salary]

    @classmethod
    def from_json(cls, data: dict) -> "CompanyInfo":
        return cls(**{k: data.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class CrawlResult:
    """单次爬取结果"""
    data: List[CompanyInfo]
    status: str          # CRAWL_OK / CRAWL_BLOCKED
    message: str         # 状态说明