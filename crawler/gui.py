#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI 应用 — 招聘平台公司信息查询
"""

import csv
import json
import threading
import time
import random
from datetime import datetime
from threading import Event
from typing import List

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont

from .config import (
    PLATFORMS, CITIES, CRAWL_OK, CRAWL_BLOCKED,
    BG, CARD_BG, PRIMARY, TEXT_DARK, TEXT_LIGHT, ACCENT, DANGER,
)
from .models import CompanyInfo
from .engine import CrawlerEngine
from .parsers import PLATFORM_CONFIG


class CrawlerApp:
    """招聘平台公司信息查询 GUI 主程序"""

    PLACEHOLDER_TEXT = "请输入搜索关键词，如：Python开发"
    PLACEHOLDER_FG = "#94A3B8"
    ENTRY_NORMAL_FG = "#0F172A"
    SURFACE = "#FFFFFF"
    SURFACE_SOFT = "#F8FAFC"
    BORDER = "#E2E8F0"
    BRAND_DARK = "#0F3D75"

    def __init__(self):
        self.engine = CrawlerEngine()
        self.results: List[CompanyInfo] = []
        self.platform_vars = {}
        self._placeholder_active = True
        self._crawl_stop = False
        self._crawl_in_progress = False
        self._stop_event = Event()
        self._login_done_event = Event()
        self._login_cancel_event = Event()
        self._login_dialog = None
        self._pending_rows: List[CompanyInfo] = []
        self._flush_after_id = None

        self.root = tk.Tk()
        self.root.title("招聘平台公司信息查询")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        self.root.configure(bg=BG)

        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1180) // 2
        y = (sh - 760) // 2
        self.root.geometry(f"1180x760+{x}+{y}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._init_fonts()
        self._setup_styles()
        self._build_ui()

    def _init_fonts(self):
        self.FONT_BOLD_18 = tkfont.Font(family="Microsoft YaHei", size=18, weight="bold")
        self.FONT_BOLD_15 = tkfont.Font(family="Microsoft YaHei", size=15, weight="bold")
        self.FONT_BOLD_14 = tkfont.Font(family="Microsoft YaHei", size=14, weight="bold")
        self.FONT_BOLD_13 = tkfont.Font(family="Microsoft YaHei", size=13, weight="bold")
        self.FONT_BOLD_12 = tkfont.Font(family="Microsoft YaHei", size=12, weight="bold")
        self.FONT_BOLD_11 = tkfont.Font(family="Microsoft YaHei", size=11, weight="bold")
        self.FONT_BOLD_10 = tkfont.Font(family="Microsoft YaHei", size=10, weight="bold")
        self.FONT_16 = tkfont.Font(family="Microsoft YaHei", size=16)
        self.FONT_15 = tkfont.Font(family="Microsoft YaHei", size=15)
        self.FONT_13 = tkfont.Font(family="Microsoft YaHei", size=13)
        self.FONT_12 = tkfont.Font(family="Microsoft YaHei", size=12)
        self.FONT_11 = tkfont.Font(family="Microsoft YaHei", size=11)
        self.FONT_10 = tkfont.Font(family="Microsoft YaHei", size=10)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview", background=self.SURFACE, fieldbackground=self.SURFACE,
            foreground=TEXT_DARK, font=self.FONT_11, rowheight=34,
            borderwidth=0, relief="flat",
        )
        style.configure(
            "Treeview.Heading", font=self.FONT_BOLD_11,
            background="#EEF4FF", foreground=self.BRAND_DARK,
            borderwidth=0, relief="flat", padding=(12, 10),
        )
        style.map("Treeview",
                  background=[("selected", "#DCEBFF")],
                  foreground=[("selected", self.BRAND_DARK)])
        style.configure(
            "Horizontal.TProgressbar", troughcolor="#E2E8F0",
            background=PRIMARY, lightcolor=PRIMARY, darkcolor=PRIMARY,
            bordercolor="#E2E8F0", thickness=7,
        )
        self._cb_off, self._cb_on = self._make_checkbox_images(24)

    def _make_checkbox_images(self, size: int):
        """生成放大后的勾选框图片（Windows 原生勾选方块几乎不随字体变大）。"""
        off = tk.PhotoImage(width=size, height=size)
        on = tk.PhotoImage(width=size, height=size)
        border, empty, fill, mark = "#7A8794", "#FFFFFF", "#2E86C1", "#FFFFFF"
        for y in range(size):
            row_off = []
            row_on = []
            for x in range(size):
                edge = x < 2 or y < 2 or x >= size - 2 or y >= size - 2
                row_off.append(border if edge else empty)
                row_on.append(border if edge else fill)
            off.put("{" + " ".join(row_off) + "}", to=(0, y))
            on.put("{" + " ".join(row_on) + "}", to=(0, y))
        for i in range(int(size * 0.22), int(size * 0.45)):
            y = i + int(size * 0.27)
            if 0 <= y < size:
                on.put(mark, to=(i, y))
                if y + 1 < size:
                    on.put(mark, to=(i, y + 1))
        for i in range(int(size * 0.45), int(size * 0.78)):
            y = int(size * 1.18) - i
            if 0 <= y < size:
                on.put(mark, to=(i, y))
                if y + 1 < size:
                    on.put(mark, to=(i, y + 1))
        return off, on

    # ──────────── UI 构建 ────────────

    def _build_ui(self):
        self._build_header()
        self._build_control_panel()
        self._build_result_area()
        self._build_footer()

    def _make_label(self, parent, **kw):
        return tk.Label(parent, **kw)

    def _build_header(self):
        header = tk.Frame(self.root, bg=PRIMARY, height=82)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        title_box = tk.Frame(header, bg=PRIMARY)
        title_box.pack(side=tk.LEFT, padx=28, pady=13)
        self._make_label(title_box, text="招聘数据采集中心",
                         font=self.FONT_BOLD_18, bg=PRIMARY, fg="white").pack(anchor=tk.W)
        self._make_label(title_box, text="跨平台职位与公司信息聚合",
                         font=self.FONT_10, bg=PRIMARY, fg="#DCEBFF").pack(anchor=tk.W, pady=(2, 0))

        self.status_label = self._make_label(
            header, text="●  就绪",
            font=self.FONT_BOLD_11, bg="#2E73BE", fg="white", padx=14, pady=7,
        )
        self.status_label.pack(side=tk.RIGHT, padx=28)

    def _build_control_panel(self):
        panel = tk.Frame(self.root, bg=self.SURFACE, highlightbackground=self.BORDER,
                         highlightthickness=1)
        panel.pack(fill=tk.X, padx=22, pady=(18, 10))

        heading = tk.Frame(panel, bg=self.SURFACE)
        heading.pack(fill=tk.X, padx=22, pady=(16, 8))
        self._make_label(heading, text="检索设置", font=self.FONT_BOLD_15,
                         bg=self.SURFACE, fg=TEXT_DARK).pack(side=tk.LEFT)
        self._make_label(heading, text="选择平台、关键词和目标地区后开始采集",
                         font=self.FONT_10, bg=self.SURFACE, fg=TEXT_LIGHT).pack(side=tk.LEFT, padx=12, pady=(4, 0))

        platform_box = tk.Frame(panel, bg=self.SURFACE_SOFT, highlightbackground=self.BORDER,
                                highlightthickness=1)
        platform_box.pack(fill=tk.X, padx=22, pady=(0, 12))
        self._make_label(platform_box, text="数据源", font=self.FONT_BOLD_11,
                         bg=self.SURFACE_SOFT, fg=TEXT_DARK).grid(row=0, column=0, padx=(14, 10), pady=12, sticky=tk.W)

        for index, (key, info) in enumerate(PLATFORMS.items(), start=1):
            var = tk.BooleanVar(value=False)
            self.platform_vars[key] = var
            cb = tk.Checkbutton(
                platform_box, text=info["name"], variable=var,
                font=self.FONT_BOLD_11, bg=self.SURFACE_SOFT,
                activebackground=self.SURFACE_SOFT, selectcolor=self.SURFACE_SOFT,
                fg=info["color"],
                image=self._cb_off, selectimage=self._cb_on,
                compound=tk.LEFT, indicatoron=False,
                bd=0, highlightthickness=0, relief=tk.FLAT,
                padx=4, pady=4, cursor="hand2", anchor=tk.W,
            )
            cb.grid(row=0, column=index, padx=(0, 12), pady=7, sticky=tk.W)
        btn_frame = tk.Frame(platform_box, bg=self.SURFACE_SOFT)
        btn_frame.grid(row=0, column=len(PLATFORMS) + 2, padx=(4, 14), pady=7, sticky=tk.E)
        tk.Button(
            btn_frame, text="全选", font=self.FONT_12,
            command=self._select_all, bg="#E7F0FF", fg=self.BRAND_DARK, relief=tk.FLAT,
            cursor="hand2", padx=10, pady=4, activebackground="#D7E7FF",
        ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(
            btn_frame, text="清空", font=self.FONT_12,
            command=self._deselect_all, bg="#F1F5F9", fg=TEXT_DARK, relief=tk.FLAT,
            cursor="hand2", padx=10, pady=4, activebackground="#E2E8F0",
        ).pack(side=tk.LEFT, padx=4)

        sf = tk.Frame(panel, bg=self.SURFACE)
        sf.pack(fill=tk.X, padx=22, pady=(0, 18))

        self._make_label(
            sf, text="关键词", font=self.FONT_BOLD_11,
            bg=self.SURFACE, fg=TEXT_DARK,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.keyword_entry = tk.Entry(
            sf, font=self.FONT_13, width=34,
            relief=tk.FLAT, bd=0, fg=self.PLACEHOLDER_FG,
            bg=self.SURFACE_SOFT, highlightbackground=self.BORDER,
            highlightcolor=PRIMARY, highlightthickness=1,
        )
        self.keyword_entry.insert(0, self.PLACEHOLDER_TEXT)
        self.keyword_entry.pack(side=tk.LEFT, padx=(0, 20), ipady=10)
        self.keyword_entry.bind("<FocusIn>", self._on_focus_in)
        self.keyword_entry.bind("<FocusOut>", self._on_focus_out)
        self.keyword_entry.bind("<Return>", lambda e: self._start_crawl())

        self._make_label(
            sf, text="地区", font=self.FONT_BOLD_11,
            bg=self.SURFACE, fg=TEXT_DARK,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.city_names = list(CITIES.keys())
        self.city_var = tk.StringVar(value="北京")
        self.city_combo = ttk.Combobox(
            sf, textvariable=self.city_var, values=self.city_names,
            font=self.FONT_12, width=8, state="readonly",
        )
        self.city_combo.pack(side=tk.LEFT, padx=(0, 18), ipady=7)

        self.crawl_btn = tk.Button(
            sf, text="开始采集", font=self.FONT_BOLD_12,
            bg=PRIMARY, fg="white", activebackground="#357CC3",
            relief=tk.FLAT, padx=20, pady=10, cursor="hand2",
            command=self._start_crawl,
        )
        self.crawl_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = tk.Button(
            sf, text="停止", font=self.FONT_BOLD_11,
            bg=DANGER, fg="white", activebackground="#C0392B",
            relief=tk.FLAT, padx=15, pady=10, cursor="hand2",
            state=tk.DISABLED, command=self._stop_crawl,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.export_btn = tk.Button(
            sf, text="导出数据", font=self.FONT_BOLD_11,
            bg=ACCENT, fg="white", activebackground="#219A52",
            relief=tk.FLAT, padx=15, pady=10, cursor="hand2",
            command=self._export,
        )
        self.export_btn.pack(side=tk.LEFT)

    def _build_result_area(self):
        container = tk.Frame(self.root, bg=self.SURFACE, highlightbackground=self.BORDER,
                             highlightthickness=1)
        container.pack(fill=tk.BOTH, expand=True, padx=22, pady=(0, 12))

        result_header = tk.Frame(container, bg=self.SURFACE)
        result_header.pack(fill=tk.X, padx=20, pady=(15, 8))
        self._make_label(result_header, text="采集结果", font=self.FONT_BOLD_15,
                         bg=self.SURFACE, fg=TEXT_DARK).pack(side=tk.LEFT)
        self.result_count_label = self._make_label(
            result_header, text="0 条记录", font=self.FONT_BOLD_10,
            bg="#E7F0FF", fg=self.BRAND_DARK, padx=9, pady=4,
        )
        self.result_count_label.pack(side=tk.LEFT, padx=10)
        self.info_label = self._make_label(
            result_header, text="尚未查询，请配置检索条件后开始采集",
            font=self.FONT_10, bg=self.SURFACE, fg=TEXT_LIGHT,
        )
        self.info_label.pack(side=tk.RIGHT, pady=(4, 0))

        columns = ("platform", "name", "industry", "scale", "location",
                   "contact_person", "contact_info")
        col_names = ("平台", "公司名称", "行业", "规模", "地点", "联系人", "联系方式")

        tree_frame = tk.Frame(container, bg=self.BORDER)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 18))

        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            selectmode="browse",
        )

        widths = (70, 130, 100, 90, 90, 80, 110)
        for col, name, w in zip(columns, col_names, widths):
            self.tree.heading(col, text=name, anchor=tk.W)
            self.tree.column(col, width=w, minwidth=60, anchor=tk.W)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.tag_configure("even", background="#FFFFFF")
        self.tree.tag_configure("odd", background="#F8FAFC")

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._show_detail)

    def _build_footer(self):
        footer = tk.Frame(self.root, bg="#EAF1FA", height=34)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.pack_propagate(False)
        self.progress = ttk.Progressbar(footer, style="Horizontal.TProgressbar",
                                        mode="determinate", length=210)
        self.progress.pack(side=tk.LEFT, padx=22, pady=8)
        self.progress_label = self._make_label(
            footer, text="等待开始", font=self.FONT_10,
            bg="#EAF1FA", fg=TEXT_LIGHT,
        )
        self.progress_label.pack(side=tk.LEFT, padx=4)

    # ──────────── 交互逻辑 ────────────

    def _select_all(self):
        for var in self.platform_vars.values():
            var.set(True)

    def _deselect_all(self):
        for var in self.platform_vars.values():
            var.set(False)

    def _wait_for_login_confirmation(self, platform_name: str, timeout: int) -> bool:
        """等待人工确认；拉勾、猎聘验证页恢复后自动继续。"""
        self._login_done_event.clear()
        self._login_cancel_event.clear()
        if self._captcha_cleared_automatically(platform_name):
            return True
        self.root.after(0, self._show_login_confirmation, platform_name)
        deadline = time.monotonic() + timeout
        next_check = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if self._stop_event.is_set() or self._login_cancel_event.is_set():
                return False
            if self._login_done_event.wait(0.2):
                return True
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + 1.0
                if self._captcha_cleared_automatically(platform_name):
                    self.root.after(0, self._dismiss_login_dialog_after_auto_verify)
                    return True
        return False

    def _captcha_cleared_automatically(self, platform_name: str) -> bool:
        """只对可明确检测验证状态的平台启用自动继续。"""
        platform_key = {"拉勾网": "lagou", "猎聘": "liepin"}.get(platform_name)
        driver = self.engine._driver
        if not platform_key or driver is None:
            return False
        try:
            return not CrawlerEngine._detect_captcha(driver, PLATFORM_CONFIG[platform_key])
        except Exception:
            return False

    def _dismiss_login_dialog_after_auto_verify(self):
        """验证通过后由主线程关闭提示框，避免 Tk 跨线程访问。"""
        dialog = self._login_dialog
        if dialog and dialog.winfo_exists():
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
        self._login_dialog = None
        self.status_label.config(text="●  验证已通过，继续采集", bg="#15803D")

    def _show_login_confirmation(self, platform_name: str):
        if self._login_dialog and self._login_dialog.winfo_exists():
            return
        dlg = tk.Toplevel(self.root)
        self._login_dialog = dlg
        dlg.title(f"{platform_name} 手动验证")
        dlg.geometry("520x260")
        dlg.configure(bg=CARD_BG)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.attributes("-topmost", True)
        dlg.lift()
        dlg.focus_force()
        self.root.lift()
        self.status_label.config(text=f"等待 {platform_name} 验证确认...")

        self._make_label(
            dlg, text="请在已打开的 Chrome 窗口中完成验证",
            font=self.FONT_BOLD_13, bg=CARD_BG, fg=TEXT_DARK,
        ).pack(pady=(22, 10))
        tip = (
            "程序已打开普通 Chrome（无「自动化控制」提示）。\n"
            "拉勾网：请先在首页手动搜索关键词，再完成滑块验证。\n"
            "滑块验证通过后程序会自动继续；若未自动继续，可点击「已完成」。\n"
            "若验证失败，请在浏览器中手动刷新页面后再重试。"
            if platform_name == "拉勾网"
            else
            "程序已打开普通 Chrome（无「自动化控制」提示）。\n"
            "请在该窗口完成滑块/安全验证；若失败请先点浏览器刷新再重试。\n"
            "验证通过后会自动继续；若未自动继续，也可点击「已完成」。"
        )
        self._make_label(
            dlg,
            text=tip,
            font=self.FONT_10, bg=CARD_BG, fg=TEXT_LIGHT,
            justify=tk.LEFT,
        ).pack(padx=24)

        buttons = tk.Frame(dlg, bg=CARD_BG)
        buttons.pack(pady=20)

        def done():
            self._login_done_event.set()
            self.status_label.config(text="验证已确认，查询中...")
            dlg.destroy()
            self._login_dialog = None

        def cancel():
            self._login_cancel_event.set()
            self.status_label.config(text="就绪")
            dlg.destroy()
            self._login_dialog = None

        tk.Button(
            buttons, text="已完成", command=done,
            font=self.FONT_BOLD_11, bg=ACCENT, fg="white",
            relief=tk.FLAT, padx=20, pady=5,
        ).pack(side=tk.LEFT, padx=8)
        tk.Button(
            buttons, text="取消", command=cancel,
            font=self.FONT_11, bg="#E8EEF4", fg=TEXT_DARK,
            relief=tk.FLAT, padx=20, pady=5,
        ).pack(side=tk.LEFT, padx=8)
        dlg.protocol("WM_DELETE_WINDOW", cancel)

    # ──────────── 占位符逻辑 ────────────

    def _on_focus_in(self, event):
        if self._placeholder_active:
            self.keyword_entry.delete(0, tk.END)
            self.keyword_entry.config(fg=self.ENTRY_NORMAL_FG)
            self._placeholder_active = False

    def _on_focus_out(self, event):
        if not self.keyword_entry.get().strip():
            self.keyword_entry.delete(0, tk.END)
            self.keyword_entry.insert(0, self.PLACEHOLDER_TEXT)
            self.keyword_entry.config(fg=self.PLACEHOLDER_FG)
            self._placeholder_active = True

    def _get_keyword(self) -> str:
        if self._placeholder_active:
            return ""
        return self.keyword_entry.get().strip()

    # ──────────── 查询控制 ────────────

    def _start_crawl(self):
        if self._crawl_in_progress:
            return
        selected = [k for k, v in self.platform_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("提示", "请至少选择一个招聘平台！")
            return

        keyword = self._get_keyword()
        if not keyword:
            messagebox.showwarning("提示", "请输入搜索关键词！")
            self.keyword_entry.focus_set()
            return

        city_name = self.city_var.get()
        city_codes = CITIES.get(city_name, {})
        self._crawl_stop = False
        self._crawl_in_progress = True
        self._stop_event.clear()
        self.crawl_btn.config(state=tk.DISABLED, text="采集中...")
        self.stop_btn.config(state=tk.NORMAL)
        self.status_label.config(text=f"●  正在采集 · {city_name}", bg="#2563A8")
        self.info_label.config(text=f"正在准备查询  |  关键词：{keyword}  |  地区：{city_name}")
        self.progress_label.config(text="")
        self.results.clear()
        self._pending_rows.clear()
        if self._flush_after_id is not None:
            self.root.after_cancel(self._flush_after_id)
            self._flush_after_id = None
        items = self.tree.get_children()
        if items:
            self.tree.delete(*items)
        self._update_result_count()

        self.progress["maximum"] = len(selected)
        self.progress["value"] = 0

        thread = threading.Thread(
            target=self._crawl_worker,
            args=(selected, keyword, city_codes, city_name),
            daemon=True,
        )
        thread.start()

    def _crawl_worker(self, platforms, keyword, city_codes, city_name):
        statuses = []
        for i, pk in enumerate(platforms):
            if self._crawl_stop:
                statuses.append(("aborted", ""))
                self.root.after(0, lambda: self._crawl_done(True, statuses))
                return
            pname = PLATFORMS[pk]["name"]
            city_code = city_codes.get(pk, "")
            def _set_platform_status(n=pname, idx=i + 1, total=len(platforms)):
                self.info_label.config(text=f"正在查询 {n}...")
                self.progress_label.config(text=f"{idx}/{total} 平台")
            self.root.after(0, _set_platform_status)
            try:
                from .accounts import resolve_credentials

                result = self.engine.crawl(
                    pk, keyword, city_code=city_code, city_name=city_name,
                    stop_check=lambda: self._crawl_stop,
                    log_callback=lambda msg: print(msg),
                    stop_event=self._stop_event,
                    page_callback=self._on_page_collected,
                    credentials=resolve_credentials(
                        pk,
                    ) if pk in ("boss", "liepin") else None,
                    login_confirmation=self._wait_for_login_confirmation if pk in ("boss", "lagou", "liepin") else None,
                )
                if result.status == CRAWL_OK:
                    statuses.append(("ok", f"{pname}: {result.message}"))
                else:
                    statuses.append(("blocked", f"{pname}: {result.message}"))
            except Exception as e:
                statuses.append(("error", f"{pname}: {e}"))
            self.root.after(0, lambda c=i+1, t=len(platforms): self._update_progress(c, t))

        self.root.after(0, lambda: self._crawl_done(False, statuses))

    def _stop_crawl(self):
        self._crawl_stop = True
        self._stop_event.set()
        self._login_cancel_event.set()
        self.status_label.config(text="●  正在停止...", bg="#B45309")
        self.stop_btn.config(state=tk.DISABLED)

    def _on_page_collected(self, platform_name, page, data, total):
        self.root.after(
            0,
            lambda: self._handle_page_data(platform_name, page, data, total),
        )

    def _handle_page_data(self, platform_name, page, data, total):
        self.results.extend(data)
        self._append_rows(data)
        self._update_result_count()
        self.info_label.config(
            text=f"{platform_name}  第 {page} 页新增 {len(data)} 条  |  当前平台累计 {total} 条"
        )
        self.progress_label.config(text=f"{platform_name} · 第 {page} 页 · 累计 {total} 条")

    def _append_rows(self, data: List[CompanyInfo]):
        self._pending_rows.extend(data)
        if self._flush_after_id is None:
            self._flush_after_id = self.root.after(16, self._flush_pending_rows)

    def _flush_pending_rows(self):
        """分批插入表格，避免一次渲染大量数据时冻结界面。"""
        self._flush_after_id = None
        batch = self._pending_rows[:200]
        del self._pending_rows[:200]
        start_index = len(self.tree.get_children())
        for index, c in enumerate(batch, start=start_index):
            self.tree.insert("", tk.END, tags=("even" if index % 2 == 0 else "odd",), values=(
                c.platform, c.name, c.industry, c.scale, c.location,
                c.contact_person, c.contact_info,
            ))
        if self._pending_rows:
            self._flush_after_id = self.root.after(1, self._flush_pending_rows)

    def _update_result_count(self):
        self.result_count_label.config(text=f"{len(self.results)} 条记录")

    def _update_progress(self, current, total):
        self.progress["value"] = current
        self.progress_label.config(text=f"{current}/{total} 平台完成")

    def _crawl_done(self, stopped=False, statuses=None):
        self._crawl_in_progress = False
        self.crawl_btn.config(state=tk.NORMAL, text="开始采集")
        self.stop_btn.config(state=tk.DISABLED)
        n = len(self.results)
        statuses = statuses or []
        if stopped:
            self.info_label.config(text=f"查询已中止  |  已获取 {n} 条")
            self.status_label.config(text="●  已中止", bg="#B45309")
            self.progress_label.config(text="已中止")
        elif statuses:
            ok_count = sum(1 for s, _ in statuses if s == "ok")
            blocked_count = sum(1 for s, _ in statuses if s == "blocked")
            summary = f"共获取 {n} 条数据"
            if blocked_count:
                summary += f"  {ok_count} 平台成功，{blocked_count} 平台被拦截"
            self.info_label.config(text=summary)
            self.status_label.config(text="●  采集完成", bg="#15803D")
            self.progress_label.config(text="全部完成")

            blocked_msgs = [msg for st, msg in statuses if st == "blocked"]
            if blocked_msgs:
                detail = "\n\n".join(blocked_msgs)
                ok_names = [msg for st, msg in statuses if st == "ok"]
                ok_text = "\n".join(ok_names) if ok_names else "无"
                messagebox.showinfo(
                    "查询结果报告",
                    f"【成功平台】\n{ok_text}\n\n"
                    f"【被拦截平台】\n{detail}\n\n"
                    f"共获取 {n} 条招聘数据。"
                )

    # ──────────── 详情查看 ────────────

    def _show_detail(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        item_id = sel[0]
        all_ids = self.tree.get_children()
        try:
            idx = all_ids.index(item_id)
        except ValueError:
            return
        if idx >= len(self.results):
            return
        c = self.results[idx]

        detail_win = tk.Toplevel(self.root)
        detail_win.title(f"公司详情  {c.name}")
        detail_win.geometry("520x420")
        detail_win.configure(bg=CARD_BG)
        detail_win.resizable(False, False)
        detail_win.update_idletasks()
        sw = detail_win.winfo_screenwidth()
        sh = detail_win.winfo_screenheight()
        detail_win.geometry(f"520x420+{(sw-520)//2}+{(sh-420)//2}")

        fields = [
            ("来源平台", c.platform), ("公司名称", c.name),
            ("行业", c.industry), ("公司规模", c.scale),
            ("地点", c.location),
            ("联系人", c.contact_person), ("联系方式", c.contact_info),
            ("公司简介", c.description),
        ]

        y = 16
        for label, value in fields:
            self._make_label(
                detail_win, text=f"{label}：",
                font=self.FONT_BOLD_12,
                bg=CARD_BG, fg=TEXT_DARK, anchor=tk.NW,
            ).place(x=20, y=y)
            self._make_label(
                detail_win, text=value or "暂无",
                font=self.FONT_12,
                bg=CARD_BG, fg=TEXT_LIGHT,
                anchor=tk.NW, wraplength=320, justify=tk.LEFT,
            ).place(x=120, y=y)
            y += 42

        tk.Button(
            detail_win, text="关闭", font=self.FONT_12,
            bg=PRIMARY, fg="white", relief=tk.FLAT,
            padx=24, pady=4, command=detail_win.destroy, cursor="hand2",
        ).place(x=210, y=y + 10)

    # ──────────── 导出 ────────────

    def _export(self):
        if not self.results:
            messagebox.showinfo("提示", "暂无数据可导出")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("JSON 文件", "*.json")],
            initialfile=f"招聘数据_{datetime.now():%Y%m%d_%H%M%S}",
        )
        if not path:
            return

        try:
            if path.endswith(".json"):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump([c.__dict__ for c in self.results], f,
                              ensure_ascii=False, indent=2)
            else:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "平台", "公司名称", "行业", "规模", "地点",
                        "联系人", "联系方式", "公司简介",
                    ])
                    for c in self.results:
                        writer.writerow([
                            c.platform, c.name, c.industry, c.scale, c.location,
                            c.contact_person, c.contact_info, c.description,
                        ])
            messagebox.showinfo("成功", f"已导出 {len(self.results)} 家公司至：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.engine.close()

    def _on_close(self):
        self._crawl_stop = True
        self._stop_event.set()
        self._login_cancel_event.set()
        self.root.destroy()
