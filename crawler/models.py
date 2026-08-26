#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型定义
"""

from dataclasses import dataclass, fields
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
    contact_person: str = ""   # 联系人
    contact_info: str = ""     # 联系方式（电话/邮箱等）

    def to_list(self):
        return [
            self.platform, self.name, self.industry, self.scale,
            self.stage, self.description, self.location,
            self.hot_jobs, self.salary, self.contact_person, self.contact_info,
        ]

    @classmethod
    def from_json(cls, data: dict) -> "CompanyInfo":
        valid = {f.name for f in fields(cls)}
        return cls(**{k: data.get(k, "") for k in valid})


@dataclass
class CrawlResult:
    """单次爬取结果"""
    data: List[CompanyInfo]
    status: str          # CRAWL_OK / CRAWL_BLOCKED
    message: str         # 状态说明
