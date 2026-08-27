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
from .auth import Credentials
from .engine import CrawlerEngine


class CrawlerApp:
    """招聘平台公司信息查询 GUI 主程序"""

    PLACEHOLDER_TEXT = "请输入搜索关键词，如：Python开发"
    PLACEHOLDER_FG   = "#B0B8C1"
    ENTRY_NORMAL_FG  = "#2C3E50"

    def __init__(self):
        self.engine = CrawlerEngine()
        self.results: List[CompanyInfo] = []
        self.platform_vars = {}
        self._placeholder_active = True
        self._crawl_stop = False
        self._stop_event = Event()
        self._login_done_event = Event()
        self._login_cancel_event = Event()
        self._boss_credentials = None
        self._boss_logged_in = False
        self._login_dialog = None

        self.root = tk.Tk()
        self.root.title("招聘平台公司信息查询")
        self.root.geometry("1100x720")
        self.root.minsize(900, 600)
        self.root.configure(bg=BG)

        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1100) // 2
        y = (sh - 720) // 2
        self.root.geometry(f"1100x720+{x}+{y}")
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
        style.configure("Treeview",
                        background=CARD_BG, fieldbackground=CARD_BG,
                        font=self.FONT_11, rowheight=30)
        style.configure("Treeview.Heading",
                        font=self.FONT_BOLD_11,
                        background="#E8EEF4", foreground=TEXT_DARK)
        style.map("Treeview",
                  background=[("selected", "#D5E8FF")],
                  foreground=[("selected", PRIMARY)])
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
        header = tk.Frame(self.root, bg=PRIMARY, height=56)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        self._make_label(
            header, text="招聘平台公司信息查询",
            font=self.FONT_BOLD_18, bg=PRIMARY, fg="white",
        ).pack(side=tk.LEFT, padx=20, pady=12)

        self.status_label = self._make_label(
            header, text="就绪",
            font=self.FONT_12, bg=PRIMARY, fg="#D5E8FF",
        )
        self.status_label.pack(side=tk.RIGHT, padx=20)

    def _build_control_panel(self):
        panel = tk.Frame(self.root, bg=CARD_BG)
        panel.pack(fill=tk.X, padx=16, pady=(12, 4))

        # ── 平台选择 ──
        pf = tk.LabelFrame(
            panel, text="选择平台",
            font=self.FONT_BOLD_15,
            bg=CARD_BG, fg=TEXT_DARK, padx=16, pady=14,
            labelanchor="nw",
        )
        pf.pack(fill=tk.X, padx=12, pady=(10, 6))

        for key, info in PLATFORMS.items():
            var = tk.BooleanVar(value=False)
            self.platform_vars[key] = var
            cb = tk.Checkbutton(
                pf, text=info["name"], variable=var,
                font=self.FONT_15, bg=CARD_BG,
                activebackground=CARD_BG, selectcolor=CARD_BG,
                fg=info["color"],
                image=self._cb_off, selectimage=self._cb_on,
                compound=tk.LEFT, indicatoron=False,
                bd=0, highlightthickness=0, relief=tk.FLAT,
                padx=6, pady=4, cursor="hand2",
            )
            cb.pack(side=tk.LEFT, padx=(0, 24))
            if key == "boss" and info.get("requires_login"):
                self._boss_login_label = self._make_label(
                    pf, text="需登录", font=self.FONT_BOLD_12,
                    fg="#E67E22", bg=CARD_BG, cursor="hand2",
                )
                self._boss_login_label.pack(side=tk.LEFT, padx=(0, 24))
                self._boss_login_label.bind(
                    "<Button-1>", lambda e: self._open_login_settings()
                )

        btn_frame = tk.Frame(pf, bg=CARD_BG)
        btn_frame.pack(side=tk.LEFT)
        tk.Button(
            btn_frame, text="全选", font=self.FONT_12,
            command=self._select_all, bg="#EBF5FB", relief=tk.FLAT,
            cursor="hand2", padx=10, pady=4,
        ).pack(side=tk.LEFT, padx=(12, 4))
        tk.Button(
            btn_frame, text="全不选", font=self.FONT_12,
            command=self._deselect_all, bg="#EBF5FB", relief=tk.FLAT,
            cursor="hand2", padx=10, pady=4,
        ).pack(side=tk.LEFT, padx=4)

        # ── 搜索栏 ──
        sf = tk.Frame(panel, bg=CARD_BG)
        sf.pack(fill=tk.X, padx=12, pady=(8, 12))

        self._make_label(
            sf, text="搜索关键词：", font=self.FONT_15,
            bg=CARD_BG, fg=TEXT_DARK,
        ).pack(side=tk.LEFT)

        self.keyword_entry = tk.Entry(
            sf, font=self.FONT_16, width=30,
            relief=tk.SOLID, bd=1, fg=self.PLACEHOLDER_FG,
        )
        self.keyword_entry.insert(0, self.PLACEHOLDER_TEXT)
        self.keyword_entry.pack(side=tk.LEFT, padx=(6, 14), ipady=6)
        self.keyword_entry.bind("<FocusIn>", self._on_focus_in)
        self.keyword_entry.bind("<FocusOut>", self._on_focus_out)
        self.keyword_entry.bind("<Return>", lambda e: self._start_crawl())

        self._make_label(
            sf, text="地区：", font=self.FONT_15,
            bg=CARD_BG, fg=TEXT_DARK,
        ).pack(side=tk.LEFT)

        self.city_names = list(CITIES.keys())
        self.city_var = tk.StringVar(value="北京")
        self.city_combo = ttk.Combobox(
            sf, textvariable=self.city_var, values=self.city_names,
            font=self.FONT_15, width=7, state="readonly",
        )
        self.city_combo.pack(side=tk.LEFT, padx=(6, 14), ipady=4)

        self.crawl_btn = tk.Button(
            sf, text="开始查询", font=self.FONT_BOLD_14,
            bg=PRIMARY, fg="white", activebackground="#3A7BC8",
            relief=tk.FLAT, padx=22, pady=6, cursor="hand2",
            command=self._start_crawl,
        )
        self.crawl_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = tk.Button(
            sf, text="停止", font=self.FONT_BOLD_13,
            bg=DANGER, fg="white", activebackground="#C0392B",
            relief=tk.FLAT, padx=16, pady=6, cursor="hand2",
            state=tk.DISABLED, command=self._stop_crawl,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.export_btn = tk.Button(
            sf, text="导出结果", font=self.FONT_13,
            bg=ACCENT, fg="white", activebackground="#219A52",
            relief=tk.FLAT, padx=16, pady=6, cursor="hand2",
            command=self._export,
        )
        self.export_btn.pack(side=tk.LEFT)

    def _build_result_area(self):
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 4))

        self.info_label = self._make_label(
            container, text="尚未查询，请选择平台并点击开始查询",
            font=self.FONT_11, bg=BG, fg=TEXT_LIGHT,
        )
        self.info_label.pack(anchor=tk.W, pady=(4, 2))

        columns = ("platform", "name", "industry", "scale", "location",
                   "contact_person", "contact_info")
        col_names = ("平台", "公司名称", "行业", "规模", "地点", "联系人", "联系方式")

        tree_frame = tk.Frame(container, bg=CARD_BG)
        tree_frame.pack(fill=tk.BOTH, expand=True)

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

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._show_detail)

    def _build_footer(self):
        footer = tk.Frame(self.root, bg="#E8EEF4", height=28)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.pack_propagate(False)
        self.progress = ttk.Progressbar(footer, mode="determinate", length=200)
        self.progress.pack(side=tk.LEFT, padx=12, pady=4)
        self.progress_label = self._make_label(
            footer, text="", font=self.FONT_10,
            bg="#E8EEF4", fg=TEXT_LIGHT,
        )
        self.progress_label.pack(side=tk.LEFT, padx=4)

    # ──────────── 交互逻辑 ────────────

    def _select_all(self):
        for var in self.platform_vars.values():
            var.set(True)

    def _deselect_all(self):
        for var in self.platform_vars.values():
            var.set(False)

    def _set_boss_logged_in(self):
        self._boss_logged_in = True
        self._boss_login_label.config(text="已登录", fg="#27AE60")

    def _reset_boss_login_status(self):
        self._boss_logged_in = False
        self._boss_credentials = None
        self._boss_login_label.config(text="需登录", fg="#E67E22")

    # ──────────── 浏览器登录 ────────────

    def _open_login_settings(self):
        """收集 Boss 临时凭据并立即启动浏览器登录流程。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("Boss直聘登录设置")
        dlg.geometry("480x300")
        dlg.configure(bg=CARD_BG)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        self._make_label(
            dlg, text="Boss直聘临时登录信息",
            font=self.FONT_BOLD_14, bg=CARD_BG, fg=TEXT_DARK,
        ).pack(pady=(20, 8))
        self._make_label(
            dlg,
            text="可在此临时输入；留空则自动读取项目根目录 .credentials.json。\n"
                 "短信、滑块或验证码必须由你手动完成。",
            font=self.FONT_10, bg=CARD_BG, fg=TEXT_LIGHT,
            justify=tk.LEFT,
        ).pack(padx=28, anchor=tk.W)

        form = tk.Frame(dlg, bg=CARD_BG)
        form.pack(fill=tk.X, padx=28, pady=14)
        self._make_label(form, text="账号：", font=self.FONT_11,
                 bg=CARD_BG, fg=TEXT_DARK).grid(row=0, column=0, pady=6, sticky=tk.E)
        username = tk.Entry(form, font=self.FONT_11, width=32)
        username.grid(row=0, column=1, pady=6)
        self._make_label(form, text="密码：", font=self.FONT_11,
                 bg=CARD_BG, fg=TEXT_DARK).grid(row=1, column=0, pady=6, sticky=tk.E)
        password = tk.Entry(form, font=self.FONT_11, width=32, show="*")
        password.grid(row=1, column=1, pady=6)

        if self._boss_credentials:
            username.insert(0, self._boss_credentials.username)

        def save():
            if self._boss_credentials:
                self._boss_credentials.clear()
            self._boss_credentials = Credentials(
                username=username.get().strip(),
                password=password.get(),
            )
            dlg.destroy()
            self.status_label.config(text="Boss 登录信息已准备，正在打开浏览器...")
            threading.Thread(target=self._do_boss_login_background, daemon=True).start()

        tk.Button(
            dlg, text="确定并登录", command=save, font=self.FONT_BOLD_11,
            bg=PRIMARY, fg="white", relief=tk.FLAT, padx=24, pady=5,
        ).pack()

    def _do_boss_login_background(self):
        """在后台线程中执行 Boss 登录流程。"""
        try:
            from .auth import LoginCoordinator
            driver = self.engine._ensure_driver(
                "boss", None, lambda msg: print(msg), "Boss直聘",
            )
            auth = LoginCoordinator(
                driver, self._stop_event,
                log=lambda msg: print(msg),
            )
            success = auth.ensure_boss_login(
                self._boss_credentials,
                self._wait_for_login_confirmation,
            )
            if success:
                if self._boss_credentials:
                    self._boss_credentials.clear()
                self.root.after(0, self._set_boss_logged_in)
            else:
                self.root.after(0, self._reset_boss_login_status)
                self.root.after(0, lambda: messagebox.showwarning(
                    "登录失败", "Boss直聘登录未完成，状态恢复为需登录。"))
        except Exception as e:
            self.root.after(0, self._reset_boss_login_status)
            self.root.after(0, lambda: messagebox.showerror(
                "登录出错", f"Boss直聘登录过程出错：{e}"))

    def _wait_for_login_confirmation(self, platform_name: str, timeout: int) -> bool:
        """工作线程等待主线程中的人工登录确认。"""
        self._login_done_event.clear()
        self._login_cancel_event.clear()
        self.root.after(0, self._show_login_confirmation, platform_name)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop_event.is_set() or self._login_cancel_event.is_set():
                return False
            if self._login_done_event.wait(0.2):
                return True
        return False

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
        self._make_label(
            dlg,
            text="程序已打开普通 Chrome（无「自动化控制」提示）。\n"
                 "请在该窗口完成滑块/安全验证；若失败请先点浏览器刷新再重试。\n"
                 "确认页面正常显示后，再点击「已完成」。",
            font=self.FONT_10, bg=CARD_BG, fg=TEXT_LIGHT,
            justify=tk.LEFT,
        ).pack(padx=24)

        buttons = tk.Frame(dlg, bg=CARD_BG)
        buttons.pack(pady=20)

        def done():
            self._login_done_event.set()
            self.status_label.config(text="验证已确认，查询中...")
            dlg.destroy()

        def cancel():
            self._login_cancel_event.set()
            self.status_label.config(text="就绪")
            dlg.destroy()

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
        self._stop_event.clear()
        if "boss" in selected and self._boss_credentials is None and not self._boss_logged_in:
            from .accounts import load_platform_credentials
            self._boss_credentials = load_platform_credentials("boss") or Credentials()
        self.crawl_btn.config(state=tk.DISABLED, text="查询中...")
        self.stop_btn.config(state=tk.NORMAL)
        self.status_label.config(text=f"查询中  {city_name}...")
        self.info_label.config(text=f"正在准备查询  |  关键词：{keyword}  |  地区：{city_name}")
        self.progress_label.config(text="")
        self.results.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

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
                        self._boss_credentials if pk == "boss" else None,
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
        self.status_label.config(text="中止中...")
        self.stop_btn.config(state=tk.DISABLED)

    def _on_page_collected(self, platform_name, page, data, total):
        self.root.after(
            0,
            lambda: self._handle_page_data(platform_name, page, data, total),
        )

    def _handle_page_data(self, platform_name, page, data, total):
        self.results.extend(data)
        self._append_rows(data)
        self.info_label.config(
            text=f"{platform_name}  第 {page} 页新增 {len(data)} 条  |  当前平台累计 {total} 条"
        )
        self.progress_label.config(text=f"{platform_name} · 第 {page} 页 · 累计 {total} 条")

    def _append_rows(self, data: List[CompanyInfo]):
        tree = self.tree
        for c in data:
            tree.insert("", tk.END, values=(
                c.platform, c.name, c.industry, c.scale, c.location,
                c.contact_person, c.contact_info,
            ))

    def _update_progress(self, current, total):
        self.progress["value"] = current
        self.progress_label.config(text=f"{current}/{total} 平台完成")

    def _crawl_done(self, stopped=False, statuses=None):
        self.crawl_btn.config(state=tk.NORMAL, text="开始查询")
        self.stop_btn.config(state=tk.DISABLED)
        n = len(self.results)
        statuses = statuses or []
        if self._boss_credentials and not self._boss_logged_in:
            self._boss_credentials.clear()
            self._boss_credentials = None

        if stopped:
            self.info_label.config(text=f"查询已中止  |  已获取 {n} 条")
            self.status_label.config(text="已中止")
            self.progress_label.config(text="已中止")
        elif statuses:
            ok_count = sum(1 for s, _ in statuses if s == "ok")
            blocked_count = sum(1 for s, _ in statuses if s == "blocked")
            summary = f"共获取 {n} 条数据"
            if blocked_count:
                summary += f"  {ok_count} 平台成功，{blocked_count} 平台被拦截"
            self.info_label.config(text=summary)
            self.status_label.config(text="查询完成")
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
        if self._boss_credentials:
            self._boss_credentials.clear()
            self._boss_credentials = None
        self.root.destroy()