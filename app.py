import sys
import ctypes

# 开启 Windows 真正的高清 DPI 缩放支持 (彻底解决高分屏/笔记本文字与UI发虚模糊问题)
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per Monitor DPI Aware v2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# -*- coding: utf-8 -*-
"""
云端极速上传器 v2.0 (Google Drive High-Speed Uploader Client)
专为大容量视频素材、高频并发与 VPN/弱网环境设计的桌面客户端
参考极简暗黑科技美学与 5TB Google Drive 稳定传输规范
"""

import os
import sys
import json
import time
import math
import random
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import webbrowser
import requests

import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

# 尝试载入拖拽扩展库
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    TkinterDnD = None
    DND_FILES = None
    HAS_DND = False

# 基础路径与配置
if getattr(sys, "frozen", False):
    APP_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".gdrive_uploader_client_cfg.json")
LOGO_PNG = os.path.join(APP_DIR, "logo.png")
LOGO_SMALL_PNG = os.path.join(APP_DIR, "logo_small.png")
LOGO_CARD_PNG = os.path.join(APP_DIR, "logo_card.png")
ICON_ICO = os.path.join(APP_DIR, "app_icon.ico")

GROUPS_LIST = ["视频组", "效果组", "作图组", "新人拍摄素材"]

# 默认配置 (优先支持从环境变量读取，提升安全性与自动化部署灵活性)
DEFAULT_WEB_APP_URL = os.environ.get("GDRIVE_WEB_APP_URL", "")

DEFAULT_CONFIG = {
    "web_app_url": DEFAULT_WEB_APP_URL,
    "last_group": "视频组",
    "last_uploader": "",
    "last_receiver": "",
    "concurrency": 2,
    "chunk_size_mb": 4,
    "proxy_url": os.environ.get("GDRIVE_PROXY_URL", "")
}

# ---------------- 安全防护与校验辅助函数 ----------------
def sanitize_text_input(val, max_len=120):
    """
    清洗用户输入的姓名与字段：
    1. 剔除控制字符、换行符及空字节
    2. 替换路径穿越字符 / 与 \\
    3. 防御表格公式注入 (CSV / Formula Injection): 避免以 =、+、-、@ 开头
    """
    if not val:
        return ""
    cleaned = "".join(ch for ch in str(val) if ch.isprintable() and ch not in "\r\n\t\0")
    cleaned = cleaned.replace("\\", "_").replace("/", "-").strip()
    while cleaned and cleaned[0] in ('=', '+', '-', '@', '\t'):
        cleaned = cleaned[1:].strip()
    return cleaned[:max_len]

def sanitize_filename(name):
    """
    清洗上传文件名，防止路径穿越攻击 (../ 或 ..\\) 及控制字符
    """
    if not name:
        return "unnamed_file"
    base = os.path.basename(name)
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in "\r\n\t\0")
    cleaned = cleaned.replace("..", "_").replace("/", "_").replace("\\", "_").strip()
    return cleaned[:255] if cleaned else "unnamed_file"

def is_safe_upload_url(url):
    """
    校验云端下发的 Resumable 分块上传地址是否为官方 Google 安全通道 (防止客户端 SSRF / 任意目标上传)
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme.lower() != "https":
            return False
        hostname = (parsed.hostname or "").lower()
        if hostname == "googleapis.com" or hostname.endswith(".googleapis.com") or \
           hostname == "google.com" or hostname.endswith(".google.com"):
            return True
        return False
    except Exception:
        return False

def is_safe_folder_url(url):
    """
    校验云端返回的文件夹链接是否为合法 Google Drive 链接 (防止恶意伪造协议或本地任意文件执行)
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme.lower() != "https":
            return False
        hostname = (parsed.hostname or "").lower()
        if hostname == "google.com" or hostname.endswith(".google.com"):
            return True
        return False
    except Exception:
        return False

def validate_proxy_url(proxy_url):
    """
    校验本地代理地址格式，仅支持规范的 http/https/socks5 协议
    """
    if not proxy_url or not proxy_url.strip():
        return True, ""
    cleaned = proxy_url.strip()
    try:
        parsed = urllib.parse.urlparse(cleaned)
        if parsed.scheme.lower() not in ("http", "https", "socks5", "socks5h"):
            return False, "代理协议仅支持 http://, https:// 或 socks5://"
        if not parsed.hostname:
            return False, "代理地址必须包含有效的主机名或IP地址"
        if parsed.port and not (1 <= parsed.port <= 65535):
            return False, "代理端口必须在 1-65535 范围内"
        return True, cleaned
    except Exception as e:
        return False, f"代理格式无效: {e}"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = DEFAULT_CONFIG.copy()
                cfg.update(data)
                if cfg.get("proxy_url"):
                    ok, _ = validate_proxy_url(cfg["proxy_url"])
                    if not ok:
                        cfg["proxy_url"] = ""
                return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        if sys.platform != "win32":
            # POSIX / Mac 设置严格文件权限 0600 (仅当前用户读写)
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(CONFIG_FILE, flags, 0o600)
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        else:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("保存配置失败:", e)

def format_size(bytes_val):
    if bytes_val <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(bytes_val, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_val / p, 2)
    return f"{s} {units[i]}"

def format_speed(bps):
    if bps <= 0:
        return "0.0 MB/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.1f} MB/s"

def format_seconds(seconds):
    if seconds is None or seconds < 0 or seconds > 86400 * 7:
        return "--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

# 基础窗口类：兼容 TkinterDnD 与 CustomTkinter
BaseClass = ctk.CTk
if HAS_DND:
    class HybridDnDWindow(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_supported = True
            except Exception:
                self.dnd_supported = False
    BaseClass = HybridDnDWindow

class ModernUploaderApp(BaseClass):
    def __init__(self):
        super().__init__()
        
        # 外观配置：深黑科技极客风格
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("云端极速上传器 v2.0 - Google Drive 企业专线版")
        self.geometry("980x780")
        self.minsize(920, 680)
        self.configure(fg_color="#0b101b")

        # 设置图标
        if os.path.exists(ICON_ICO):
            try:
                self.iconbitmap(ICON_ICO)
            except Exception:
                pass
        
        self.logo_image = None
        self.logo_small = None
        self.logo_card = None
        
        # 优先载入高清矢量抗锯齿独立图标
        if os.path.exists(LOGO_SMALL_PNG):
            try:
                self.logo_small = tk.PhotoImage(file=LOGO_SMALL_PNG)
            except Exception:
                pass
        elif os.path.exists(LOGO_PNG):
            try:
                self.logo_small = tk.PhotoImage(file=LOGO_PNG).subsample(4, 4)
            except Exception:
                pass

        if os.path.exists(LOGO_CARD_PNG):
            try:
                self.logo_card = tk.PhotoImage(file=LOGO_CARD_PNG)
            except Exception:
                pass
        elif os.path.exists(LOGO_PNG):
            try:
                self.logo_card = tk.PhotoImage(file=LOGO_PNG).subsample(2, 2)
            except Exception:
                pass

        if os.path.exists(LOGO_PNG):
            try:
                self.logo_image = tk.PhotoImage(file=LOGO_PNG)
                self.iconphoto(False, self.logo_image)
            except Exception:
                pass

        self.cfg = load_config()
        self.files_queue = [] # 列表项字典
        self.is_uploading = False
        self.stop_requested = False
        self.current_folder_url = ""
        self.session = requests.Session()

        # 统计数据
        self.total_bytes = 0
        self.uploaded_bytes_all = 0
        self.start_upload_time = None
        self.completed_count = 0
        self.failed_count = 0

        self._build_ui()
        self._check_config_status()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        # 1. 顶栏 (Header Bar)
        self._build_header()

        # 2. 标签栏与提示条 (Tabs & Tip)
        self._build_tabs_and_tip()

        # 3. 云端环境状态卡片 (Environment Status Bar)
        self._build_environment_bar()

        # 4. 表单参数卡片 (Parameters Card)
        self._build_parameters_card()

        # 5. 主工作区 (左右双栏: 拖拽/上传区 + 实时队列与进度)
        self._build_workspace()

        # 6. 底部日志控制台 (Log Console)
        self._build_log_card()

        # 7. 底栏状态条 (Footer Bar)
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent", height=42)
        header.pack(fill="x", padx=18, pady=(10, 4))

        # 左侧：Logo + 标题 + 版本 + 标语
        left_box = ctk.CTkFrame(header, fg_color="transparent")
        left_box.pack(side="left", fill="y")

        if self.logo_small:
            logo_lbl = tk.Label(left_box, image=self.logo_small, bg="#0b101b", bd=0)
            logo_lbl.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(left_box, text="云端极速上传器", font=ctk.CTkFont(family="Microsoft YaHei", size=18, weight="bold"), text_color="#ffffff")
        title_lbl.pack(side="left", padx=(0, 6))

        ver_badge = ctk.CTkLabel(left_box, text="v2.0", fg_color="#1877f2", text_color="#ffffff", corner_radius=4, width=38, height=18, font=ctk.CTkFont(family="Microsoft YaHei", size=10, weight="bold"))
        ver_badge.pack(side="left", padx=(0, 8))

        sub_lbl = ctk.CTkLabel(left_box, text="企业多线程 · 5T高速通道 · 防写锁避让引擎", font=ctk.CTkFont(family="Microsoft YaHei", size=11), text_color="#8c9ba5")
        sub_lbl.pack(side="left")

        # 右侧：设置、并发、模式、帮助
        right_box = ctk.CTkFrame(header, fg_color="transparent")
        right_box.pack(side="right", fill="y")

        self.concurrency_badge = ctk.CTkLabel(
            right_box, 
            text=f"⚡ 并发: {self.cfg.get('concurrency', 2)} 线程", 
            fg_color="#182338", 
            text_color="#f59e0b", 
            corner_radius=6, 
            width=88, 
            height=26, 
            font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold")
        )
        self.concurrency_badge.pack(side="right", padx=(6, 0))

        cfg_btn = ctk.CTkButton(
            right_box, 
            text="⚙ 全局设置", 
            fg_color="#1c2638", 
            hover_color="#2b3b55", 
            text_color="#e2e8f0", 
            corner_radius=6, 
            width=78, 
            height=26, 
            font=ctk.CTkFont(family="Microsoft YaHei", size=11),
            command=self._show_settings_dialog
        )
        cfg_btn.pack(side="right", padx=(6, 0))

        test_btn = ctk.CTkButton(
            right_box, 
            text="🌐 握手测试", 
            fg_color="#1c2638", 
            hover_color="#2b3b55", 
            text_color="#e2e8f0", 
            corner_radius=6, 
            width=78, 
            height=26, 
            font=ctk.CTkFont(family="Microsoft YaHei", size=11),
            command=self._test_connection_async
        )
        test_btn.pack(side="right", padx=(6, 0))

        help_btn = ctk.CTkButton(
            right_box, 
            text="❓ 使用说明", 
            fg_color="#1c2638", 
            hover_color="#2b3b55", 
            text_color="#e2e8f0", 
            corner_radius=6, 
            width=72, 
            height=26, 
            font=ctk.CTkFont(family="Microsoft YaHei", size=11),
            command=self._show_help_dialog
        )
        help_btn.pack(side="right")

    def _build_tabs_and_tip(self):
        tab_frame = ctk.CTkFrame(self, fg_color="transparent", height=32)
        tab_frame.pack(fill="x", padx=18, pady=(4, 2))

        # 标签按钮 (样式还原图1)
        self.tab1 = ctk.CTkButton(tab_frame, text="批量上传云端", fg_color="#1877f2", hover_color="#1877f2", text_color="#ffffff", corner_radius=6, width=108, height=28, font=ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold"))
        self.tab1.pack(side="left", padx=(0, 6))

        self.tab2 = ctk.CTkButton(tab_frame, text="传输队列与明细", fg_color="#151f30", hover_color="#1f2c42", text_color="#94a3b8", corner_radius=6, width=118, height=28, font=ctk.CTkFont(family="Microsoft YaHei", size=12), command=self._switch_tab_queue)
        self.tab2.pack(side="left", padx=(0, 6))

        self.tab3 = ctk.CTkButton(tab_frame, text="云端目录规则预览", fg_color="#151f30", hover_color="#1f2c42", text_color="#94a3b8", corner_radius=6, width=128, height=28, font=ctk.CTkFont(family="Microsoft YaHei", size=12), command=self._show_path_preview)
        self.tab3.pack(side="left")

        # 提示条
        tip_frame = ctk.CTkFrame(self, fg_color="transparent")
        tip_frame.pack(fill="x", padx=18, pady=(2, 6))
        tip_lbl = ctk.CTkLabel(
            tip_frame, 
            text="💡 提示：支持将视频、素材文件夹直接拖入软件窗口，系统将自动按部门与人员规则直传 Google Drive 对应目录", 
            font=ctk.CTkFont(family="Microsoft YaHei", size=11), 
            text_color="#8c9ba5"
        )
        tip_lbl.pack(side="left")

    def _build_environment_bar(self):
        # 还原图1的高清环境就绪横幅
        env_frame = ctk.CTkFrame(self, fg_color="#111927", border_color="#1c283e", border_width=1, corner_radius=8, height=36)
        env_frame.pack(fill="x", padx=18, pady=(0, 8))

        left_lbl = ctk.CTkLabel(
            env_frame, 
            text="✓ 5T Google Drive 云端就绪  |  ✓ Resumable 分块断点续传  ✓ 指数退避防写锁  ✓ 多线程防锁死", 
            font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold"), 
            text_color="#22c55e"
        )
        left_lbl.pack(side="left", padx=14, pady=5)

        right_box = ctk.CTkFrame(env_frame, fg_color="transparent")
        right_box.pack(side="right", padx=10, pady=4)

        detect_btn = ctk.CTkButton(
            right_box, 
            text="检测环境", 
            fg_color="#1c283e", 
            hover_color="#293955", 
            text_color="#cbd5e1", 
            corner_radius=4, 
            width=70, 
            height=22, 
            font=ctk.CTkFont(family="Microsoft YaHei", size=10),
            command=self._test_connection_async
        )
        detect_btn.pack(side="left", padx=(0, 6))

        self.ready_badge = ctk.CTkLabel(
            right_box, 
            text="组件已就绪", 
            fg_color="#064e3b", 
            text_color="#34d399", 
            corner_radius=4, 
            width=76, 
            height=22, 
            font=ctk.CTkFont(family="Microsoft YaHei", size=10, weight="bold")
        )
        self.ready_badge.pack(side="left")

    def _build_parameters_card(self):
        card = ctk.CTkFrame(self, fg_color="#141c2c", border_color="#1e2c44", border_width=1, corner_radius=8)
        card.pack(fill="x", padx=18, pady=(0, 8))

        card_title = ctk.CTkLabel(card, text="1. 部门分组与上传分类参数", font=ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold"), text_color="#cbd5e1")
        card_title.pack(anchor="w", padx=14, pady=(8, 4))

        # 参数网格
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 8))
        grid.columnconfigure(0, weight=3)
        grid.columnconfigure(1, weight=3)
        grid.columnconfigure(2, weight=4)

        # 1. 所选分组 (云端一级目录)
        col1 = ctk.CTkFrame(grid, fg_color="transparent")
        col1.grid(row=0, column=0, sticky="ew", padx=6)
        ctk.CTkLabel(col1, text="选择分组 (云端一级目录)", font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold"), text_color="#94a3b8").pack(anchor="w", pady=(0, 2))
        
        self.group_var = ctk.StringVar(value=self.cfg.get("last_group", "视频组"))
        self.group_dropdown = ctk.CTkOptionMenu(
            col1, 
            values=GROUPS_LIST, 
            variable=self.group_var, 
            command=self._on_group_changed,
            fg_color="#1c283e", 
            button_color="#273854", 
            button_hover_color="#364d73", 
            dropdown_fg_color="#141c2c",
            dropdown_hover_color="#1f2d45",
            font=ctk.CTkFont(family="Microsoft YaHei", size=12),
            height=30
        )
        self.group_dropdown.pack(fill="x")

        # 2. 你的名字 (二级目录)
        col2 = ctk.CTkFrame(grid, fg_color="transparent")
        col2.grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkLabel(col2, text="你的名字 (二级目录 必填)", font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold"), text_color="#94a3b8").pack(anchor="w", pady=(0, 2))
        
        self.uploader_entry = ctk.CTkEntry(
            col2, 
            placeholder_text="例如: 张三", 
            fg_color="#0e1522", 
            border_color="#24344d", 
            font=ctk.CTkFont(family="Microsoft YaHei", size=12), 
            height=30
        )
        if self.cfg.get("last_uploader"):
            self.uploader_entry.insert(0, self.cfg.get("last_uploader"))
        self.uploader_entry.pack(fill="x")

        # 3. 动态接收人 / 新人名字 (四级目录)
        self.col3 = ctk.CTkFrame(grid, fg_color="transparent")
        self.col3.grid(row=0, column=2, sticky="ew", padx=6)
        
        self.receiver_label = ctk.CTkLabel(self.col3, text="接收文件的人 (必填，请输入管理员名字)", font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold"), text_color="#94a3b8")
        self.receiver_label.pack(anchor="w", pady=(0, 2))
        
        self.receiver_entry = ctk.CTkEntry(
            self.col3, 
            placeholder_text="请输入管理员名字 (例如: 组长)", 
            fg_color="#0e1522", 
            border_color="#24344d", 
            font=ctk.CTkFont(family="Microsoft YaHei", size=12), 
            height=30
        )
        if self.cfg.get("last_receiver"):
            self.receiver_entry.insert(0, self.cfg.get("last_receiver"))
        self.receiver_entry.pack(fill="x")

        # 第 2 行：复选框防冲突选项 (还原图1的4个复选框)
        chk_row = ctk.CTkFrame(card, fg_color="transparent")
        chk_row.pack(fill="x", padx=18, pady=(4, 8))

        self.chk_resumable = ctk.CTkCheckBox(chk_row, text="断点续传与重试", font=ctk.CTkFont(family="Microsoft YaHei", size=11), fg_color="#1877f2", checkbox_width=16, checkbox_height=16)
        self.chk_resumable.select()
        self.chk_resumable.pack(side="left", padx=(0, 16))

        self.chk_skip_exist = ctk.CTkCheckBox(chk_row, text="已完成则跳过", font=ctk.CTkFont(family="Microsoft YaHei", size=11), fg_color="#1877f2", checkbox_width=16, checkbox_height=16)
        self.chk_skip_exist.select()
        self.chk_skip_exist.pack(side="left", padx=(0, 16))

        self.chk_jitter = ctk.CTkCheckBox(chk_row, text="防写锁自动避让 (Jitter)", font=ctk.CTkFont(family="Microsoft YaHei", size=11), fg_color="#1877f2", checkbox_width=16, checkbox_height=16)
        self.chk_jitter.select()
        self.chk_jitter.pack(side="left", padx=(0, 16))

        self.chk_date_folder = ctk.CTkCheckBox(chk_row, text="自动建日期分类目录 (当天日期)", font=ctk.CTkFont(family="Microsoft YaHei", size=11), fg_color="#1877f2", checkbox_width=16, checkbox_height=16)
        self.chk_date_folder.select()
        self.chk_date_folder.pack(side="left")

        # 触发一次分组联动调整
        self._on_group_changed(self.group_var.get())

    def _on_group_changed(self, selected_group):
        if selected_group == "新人拍摄素材":
            self.receiver_label.configure(text="3. 新人的名字 (必填，提示：新人的名字+尾号后4位)")
            self.receiver_entry.configure(placeholder_text="新人的名字+尾号后4位 (例如: 李四8899)")
        else:
            self.receiver_label.configure(text="3. 接收文件的人 (必填，请输入管理员名字)")
            self.receiver_entry.configure(placeholder_text="请输入管理员名字 (例如: 组长)")

    def _build_workspace(self):
        # 左右两栏
        workspace = ctk.CTkFrame(self, fg_color="transparent")
        workspace.pack(fill="x", padx=18, pady=(0, 8))
        workspace.columnconfigure(0, weight=4) # 左栏 40%
        workspace.columnconfigure(1, weight=6) # 右栏 60%

        # 左栏：拖拽上传区域 + 操作按钮
        left_panel = ctk.CTkFrame(workspace, fg_color="#141c2c", border_color="#1e2c44", border_width=1, corner_radius=8)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(left_panel, text="2. 待上传素材 / 拖拽区域 (支持批量)", font=ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=12, pady=(8, 4))

        # 拖拽盒子
        self.drop_box = ctk.CTkFrame(left_panel, fg_color="#0e1522", border_color="#24344d", border_width=1, corner_radius=8, height=130)
        self.drop_box.pack(fill="x", padx=12, pady=(0, 8))
        self.drop_box.pack_propagate(False)

        # 注册拖拽事件 (若系统支持)
        if HAS_DND and getattr(self, "dnd_supported", False):
            try:
                self.drop_box.drop_target_register(DND_FILES)
                self.drop_box.dnd_bind("<<Drop>>", self._on_files_dropped)
            except Exception as e:
                print("注册拖拽监听异常:", e)

        # 拖拽区内部内容
        drop_inner = ctk.CTkFrame(self.drop_box, fg_color="transparent")
        drop_inner.place(relx=0.5, rely=0.5, anchor="center")

        if self.logo_card:
            self.logo_card_lbl = tk.Label(drop_inner, image=self.logo_card, bg="#0e1522", bd=0)
            self.logo_card_lbl.pack(pady=(0, 4))

        drop_txt1 = ctk.CTkLabel(drop_inner, text="将视频文件或文件夹拖拽至此处", font=ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold"), text_color="#e2e8f0")
        drop_txt1.pack()

        drop_txt2 = ctk.CTkLabel(drop_inner, text="支持 .mp4 .mov .mkv .ts .zip .rar 等任意素材格式", font=ctk.CTkFont(family="Microsoft YaHei", size=10), text_color="#64748b")
        drop_txt2.pack()

        # 本地添加按钮栏
        btn_bar = ctk.CTkFrame(left_panel, fg_color="transparent")
        btn_bar.pack(fill="x", padx=12, pady=(0, 8))

        add_file_btn = ctk.CTkButton(btn_bar, text="➕ 添加文件", fg_color="#1c283e", hover_color="#293955", text_color="#e2e8f0", corner_radius=4, height=28, font=ctk.CTkFont(family="Microsoft YaHei", size=11), command=self._pick_files)
        add_file_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

        add_folder_btn = ctk.CTkButton(btn_bar, text="📂 添加文件夹", fg_color="#1c283e", hover_color="#293955", text_color="#e2e8f0", corner_radius=4, height=28, font=ctk.CTkFont(family="Microsoft YaHei", size=11), command=self._pick_folder)
        add_folder_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

        clear_btn = ctk.CTkButton(btn_bar, text="🗑️ 清空", fg_color="#1c283e", hover_color="#3d2125", text_color="#e2e8f0", corner_radius=4, width=54, height=28, font=ctk.CTkFont(family="Microsoft YaHei", size=11), command=self._clear_queue)
        clear_btn.pack(side="left")

        # 核心三大执行按钮 (还原图1底部按钮)
        act_bar = ctk.CTkFrame(left_panel, fg_color="transparent")
        act_bar.pack(fill="x", padx=12, pady=(0, 10))

        self.start_btn = ctk.CTkButton(
            act_bar, 
            text="🚀 开始极速上传", 
            fg_color="#1877f2", 
            hover_color="#166fe5", 
            text_color="#ffffff", 
            corner_radius=6, 
            height=34, 
            font=ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold"),
            command=self._start_upload_action
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.stop_btn = ctk.CTkButton(
            act_bar, 
            text="⏹ 停止", 
            fg_color="#dc2626", 
            hover_color="#b91c1c", 
            text_color="#ffffff", 
            corner_radius=6, 
            width=58, 
            height=34, 
            font=ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold"),
            state="disabled",
            command=self._stop_upload_action
        )
        self.stop_btn.pack(side="left", padx=(0, 6))

        self.open_folder_btn = ctk.CTkButton(
            act_bar, 
            text="📁 打开云端目录", 
            fg_color="#1c283e", 
            hover_color="#2b3b55", 
            text_color="#e2e8f0", 
            corner_radius=6, 
            width=100, 
            height=34, 
            font=ctk.CTkFont(family="Microsoft YaHei", size=11),
            command=self._open_current_folder
        )
        self.open_folder_btn.pack(side="left")

        # 右栏：实时队列与进度
        right_panel = ctk.CTkFrame(workspace, fg_color="#141c2c", border_color="#1e2c44", border_width=1, corner_radius=8)
        right_panel.grid(row=0, column=1, sticky="nsew")

        self.queue_title_lbl = ctk.CTkLabel(right_panel, text="3. 实时队列与进度 (已选 0 个文件，共 0 B)", font=ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold"), text_color="#cbd5e1")
        self.queue_title_lbl.pack(anchor="w", padx=14, pady=(8, 4))

        # 总进度条与速度行
        prog_box = ctk.CTkFrame(right_panel, fg_color="#0e1522", border_color="#24344d", border_width=1, corner_radius=6)
        prog_box.pack(fill="x", padx=12, pady=(0, 6))

        self.overall_progress_bar = ctk.CTkProgressBar(prog_box, fg_color="#1e293b", progress_color="#1877f2", height=10)
        self.overall_progress_bar.set(0)
        self.overall_progress_bar.pack(fill="x", padx=10, pady=(8, 4))

        stat_row = ctk.CTkFrame(prog_box, fg_color="transparent")
        stat_row.pack(fill="x", padx=10, pady=(0, 6))

        self.speed_lbl = ctk.CTkLabel(stat_row, text="速度: 0.0 MB/s", font=ctk.CTkFont(family="Microsoft YaHei", size=10), text_color="#38bdf8")
        self.speed_lbl.pack(side="left")

        self.eta_lbl = ctk.CTkLabel(stat_row, text="剩余时间: --", font=ctk.CTkFont(family="Microsoft YaHei", size=10), text_color="#94a3b8")
        self.eta_lbl.pack(side="left", padx=(14, 0))

        self.stat_count_lbl = ctk.CTkLabel(stat_row, text="成功: 0 | 失败: 0", font=ctk.CTkFont(family="Microsoft YaHei", size=10), text_color="#4ade80")
        self.stat_count_lbl.pack(side="right")

        # 队列文件列表滚动视图
        self.queue_scroll = ctk.CTkScrollableFrame(right_panel, fg_color="#0e1522", border_color="#24344d", border_width=1, corner_radius=6, height=138)
        self.queue_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.empty_tip_lbl = ctk.CTkLabel(self.queue_scroll, text="暂无待上传文件，请从左侧拖入或添加素材", font=ctk.CTkFont(family="Microsoft YaHei", size=11), text_color="#64748b")
        self.empty_tip_lbl.pack(pady=40)

    def _build_log_card(self):
        log_card = ctk.CTkFrame(self, fg_color="#141c2c", border_color="#1e2c44", border_width=1, corner_radius=8)
        log_card.pack(fill="both", expand=True, padx=18, pady=(0, 6))

        log_head = ctk.CTkFrame(log_card, fg_color="transparent", height=26)
        log_head.pack(fill="x", padx=14, pady=(6, 2))

        ctk.CTkLabel(log_head, text="4. 实时运行日志与云端通信记录", font=ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold"), text_color="#cbd5e1").pack(side="left")

        clear_log_btn = ctk.CTkButton(log_head, text="清空日志", fg_color="#1c283e", hover_color="#2b3b55", text_color="#94a3b8", corner_radius=4, width=54, height=20, font=ctk.CTkFont(family="Microsoft YaHei", size=10), command=self._clear_logs)
        clear_log_btn.pack(side="right")

        # 终端风格文本框
        self.log_text = tk.Text(
            log_card, 
            bg="#070b12", 
            fg="#94a3b8", 
            font=("Consolas", 9), 
            relief="flat", 
            bd=0, 
            padx=10, 
            pady=6,
            insertbackground="#ffffff"
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # 滚动条
        scroll = tk.Scrollbar(self.log_text, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        # 配置日志颜色高亮
        self.log_text.tag_configure("time", foreground="#475569")
        self.log_text.tag_configure("info", foreground="#cbd5e1")
        self.log_text.tag_configure("success", foreground="#4ade80")
        self.log_text.tag_configure("warning", foreground="#fbbf24")
        self.log_text.tag_configure("error", foreground="#f87171")
        self.log_text.tag_configure("cyan", foreground="#38bdf8")

    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color="transparent", height=22)
        footer.pack(fill="x", padx=20, pady=(0, 6))

        self.footer_left = ctk.CTkLabel(footer, text="云端直连引擎就绪 (未完成文件支持断点续传与网络重试)", font=ctk.CTkFont(family="Microsoft YaHei", size=10), text_color="#64748b")
        self.footer_left.pack(side="left")

        footer_right = ctk.CTkLabel(footer, text="Google Drive API v3 · 5TB 专用高速通道", font=ctk.CTkFont(family="Microsoft YaHei", size=10), text_color="#475569")
        footer_right.pack(side="right")

    # ---------------- 基础辅助与日志输出 ----------------
    def log(self, text, level="info"):
        now_str = datetime.now().strftime("%H:%M:%S")
        
        def _do_append():
            self.log_text.insert("end", f"[{now_str}] ", "time")
            tag = "info"
            if level == "success" or "成功" in text:
                tag = "success"
            elif level == "warning" or "避让" in text or "重试" in text or "⚠️" in text:
                tag = "warning"
            elif level == "error" or "失败" in text or "错误" in text or "❌" in text:
                tag = "error"
            elif level == "cyan" or "就绪" in text or "通道" in text:
                tag = "cyan"
            self.log_text.insert("end", text + "\n", tag)
            self.log_text.see("end")

        self.root_schedule(_do_append)

    def root_schedule(self, callback):
        try:
            self.after(0, callback)
        except Exception:
            pass

    def _clear_logs(self):
        self.log_text.delete("1.0", "end")

    def _check_config_status(self):
        url = self.cfg.get("web_app_url", "").strip()
        if not url:
            self.log("⚠️ 提示：尚未配置 Google Apps Script 网址，请点击右上角【⚙ 全局设置】配置通道", "warning")
            self.ready_badge.configure(text="未配置网盘", fg_color="#7f1d1d", text_color="#f87171")
        else:
            self.log("✓ Google Drive 云端极速通道配置已就绪，随时可拖入素材上传", "cyan")

    # ---------------- 队列与文件选择 ----------------
    def _pick_files(self):
        paths = filedialog.askopenfilenames(
            title="选择要上传的文件 (支持多选)",
            filetypes=[
                ("所有媒体素材", "*.mp4 *.mov *.mkv *.avi *.ts *.mp3 *.wav *.png *.jpg *.jpeg *.zip *.rar *.7z *.prproj *.aep"),
                ("所有文件", "*.*")
            ]
        )
        if paths:
            self._add_files_to_queue(paths)

    def _pick_folder(self):
        folder = filedialog.askdirectory(title="选择包含素材的文件夹")
        if folder:
            paths = []
            for root_dir, _, files in os.walk(folder):
                for f in files:
                    paths.append(os.path.join(root_dir, f))
            self._add_files_to_queue(paths)

    def _on_files_dropped(self, event):
        raw = event.data
        if not raw:
            return
        # 优先使用 Tk 原生 splitlist 解析带空格与大括号的文件路径，兼容多种拖拽规范
        paths = []
        try:
            paths = list(self.tk.splitlist(raw))
        except Exception:
            if "{" in raw:
                import re
                paths = re.findall(r'\{([^}]+)\}', raw)
            else:
                paths = raw.split()

        all_files = []
        for p in paths:
            p = p.strip('"').strip("'")
            if os.path.isdir(p):
                for root_dir, _, files in os.walk(p):
                    for f in files:
                        all_files.append(os.path.join(root_dir, f))
            elif os.path.isfile(p):
                all_files.append(p)
        self._add_files_to_queue(all_files)

    def _add_files_to_queue(self, paths):
        added = 0
        existing = {item["path"] for item in self.files_queue}
        for p in paths:
            if p in existing:
                continue
            if not os.path.isfile(p):
                continue
            try:
                sz = os.path.getsize(p)
            except Exception:
                sz = 0
            
            item = {
                "path": p,
                "name": sanitize_filename(p),
                "size": sz,
                "uploaded_bytes": 0,
                "status": "就绪", # 就绪, 上传中, 成功, 失败, 重试中
                "upload_url": "",
                "folder_url": "",
                "widgets": {}
            }
            self.files_queue.append(item)
            added += 1

        if added > 0:
            self._refresh_queue_display()
            self.log(f"已成功添加 {added} 个素材到上传队列", "info")

    def _clear_queue(self):
        if self.is_uploading:
            messagebox.showwarning("提示", "正在上传中，请先点击「停止」后再清空！")
            return
        self.files_queue = []
        self._refresh_queue_display()
        self.overall_progress_bar.set(0)
        self.speed_lbl.configure(text="速度: 0.0 MB/s")
        self.eta_lbl.configure(text="剩余时间: --")
        self.stat_count_lbl.configure(text="成功: 0 | 失败: 0")
        self.log("已清空上传队列", "info")

    def _refresh_queue_display(self):
        # 清空现有子组件
        for widget in self.queue_scroll.winfo_children():
            widget.destroy()

        if not self.files_queue:
            self.empty_tip_lbl = ctk.CTkLabel(self.queue_scroll, text="暂无待上传文件，请从左侧拖入或添加素材", font=ctk.CTkFont(family="Microsoft YaHei", size=11), text_color="#64748b")
            self.empty_tip_lbl.pack(pady=40)
            self.queue_title_lbl.configure(text="3. 实时队列与进度 (已选 0 个文件，共 0 B)")
            return

        self.total_bytes = sum(item["size"] for item in self.files_queue)
        self.queue_title_lbl.configure(text=f"3. 实时队列与进度 (已选 {len(self.files_queue)} 个文件，共 {format_size(self.total_bytes)})")

        for idx, item in enumerate(self.files_queue):
            row = ctk.CTkFrame(self.queue_scroll, fg_color="#121a28", border_color="#1e2c44", border_width=1, corner_radius=6, height=36)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)

            idx_lbl = ctk.CTkLabel(row, text=f"#{idx+1}", width=28, font=ctk.CTkFont(family="Microsoft YaHei", size=10, weight="bold"), text_color="#64748b")
            idx_lbl.pack(side="left", padx=(6, 4))

            name_lbl = ctk.CTkLabel(row, text=item["name"], anchor="w", font=ctk.CTkFont(family="Microsoft YaHei", size=11), text_color="#e2e8f0")
            name_lbl.pack(side="left", fill="x", expand=True, padx=4)

            size_lbl = ctk.CTkLabel(row, text=format_size(item["size"]), width=68, anchor="e", font=ctk.CTkFont(family="Microsoft YaHei", size=10), text_color="#94a3b8")
            size_lbl.pack(side="left", padx=4)

            pbar = ctk.CTkProgressBar(row, width=80, height=8, fg_color="#1e293b", progress_color="#1877f2")
            ratio = item["uploaded_bytes"] / item["size"] if item["size"] > 0 else 0
            pbar.set(ratio)
            pbar.pack(side="left", padx=6)

            status_lbl = ctk.CTkLabel(row, text=item["status"], width=58, font=ctk.CTkFont(family="Microsoft YaHei", size=10, weight="bold"), text_color=self._get_status_color(item["status"]))
            status_lbl.pack(side="right", padx=(4, 8))

            item["widgets"] = {
                "pbar": pbar,
                "status_lbl": status_lbl,
                "row": row
            }

    def _get_status_color(self, status):
        if status == "成功":
            return "#4ade80"
        elif "上传中" in status:
            return "#38bdf8"
        elif status == "失败":
            return "#f87171"
        elif "重试" in status or "避让" in status:
            return "#fbbf24"
        return "#94a3b8"

    def _update_item_status(self, item, status, uploaded=None):
        def _do():
            item["status"] = status
            if uploaded is not None:
                item["uploaded_bytes"] = uploaded
            w = item.get("widgets", {})
            if "status_lbl" in w:
                w["status_lbl"].configure(text=status, text_color=self._get_status_color(status))
            if "pbar" in w and item["size"] > 0:
                cur = item["uploaded_bytes"] / item["size"]
                w["pbar"].set(min(1.0, max(0.0, cur)))
        self.root_schedule(_do)

    # ---------------- 上传引擎与写锁避让逻辑 ----------------
    def _start_upload_action(self):
        if self.is_uploading:
            return

        web_url = self.cfg.get("web_app_url", "").strip()
        if not web_url:
            messagebox.showerror("配置缺失", "尚未配置 Google Apps Script 网址！\n请点击右上角【⚙ 全局设置】填入脚本地址。")
            self._show_settings_dialog()
            return

        uploader = sanitize_text_input(self.uploader_entry.get().strip())
        if not uploader:
            messagebox.showwarning("必填项未填写", "请输入【你的名字】！素材需要按照你的姓名归类。")
            self.uploader_entry.focus()
            return

        receiver = sanitize_text_input(self.receiver_entry.get().strip())
        group = sanitize_text_input(self.group_var.get())
        if not receiver:
            msg = "请输入【新人的名字+尾号后4位】！" if group == "新人拍摄素材" else "请输入【接收文件的人/管理员名字】！"
            messagebox.showwarning("必填项未填写", msg)
            self.receiver_entry.focus()
            return

        # 过滤未完成文件
        pending_items = [it for it in self.files_queue if it["status"] != "成功"]
        if not pending_items:
            messagebox.showinfo("提示", "所有文件已上传完成！如需重新上传请清空后重新添加。")
            return

        # 保存用户输入
        self.cfg["last_group"] = group
        self.cfg["last_uploader"] = uploader
        self.cfg["last_receiver"] = receiver
        save_config(self.cfg)

        self.is_uploading = True
        self.stop_requested = False
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.start_upload_time = time.time()
        self.completed_count = 0
        self.failed_count = 0

        self.log("🚀 ================= 开始极速上传任务 =================", "cyan")
        date_str = datetime.now().strftime("%Y-%m-%d")
        full_dest = f"{group} / {uploader} / {date_str} / {receiver}"
        self.log(f"目标云端目录: {full_dest}", "info")
        self.log(f"待上传文件数: {len(pending_items)} 个 | 启用并发线程: {self.cfg.get('concurrency', 2)}", "info")

        # 启动后台主上传调度线程
        threading.Thread(target=self._upload_dispatcher_thread, args=(pending_items, group, uploader, receiver, date_str), daemon=True).start()

    def _stop_upload_action(self):
        if not self.is_uploading:
            return
        self.stop_requested = True
        self.log("⏹ 正在停止上传，等待当前分块传输安全中断...", "warning")
        self.stop_btn.configure(state="disabled")

    def _upload_dispatcher_thread(self, items, group, uploader, receiver, date_str):
        concurrency = int(self.cfg.get("concurrency", 2))
        chunk_size_mb = int(self.cfg.get("chunk_size_mb", 4))

        # 定时速度计算线程
        speed_stop_event = threading.Event()
        threading.Thread(target=self._monitor_speed_thread, args=(speed_stop_event,), daemon=True).start()

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = []
            for item in items:
                if self.stop_requested:
                    break
                # 在每个线程开始前加入随机微小抖动 (Jitter: 0.2s - 0.8s)，彻底消除瞬间对同个云端目录的多重写锁争夺
                if self.chk_jitter.get():
                    time.sleep(random.uniform(0.2, 0.7))
                f = executor.submit(self._upload_single_file, item, group, uploader, receiver, date_str, chunk_size_mb)
                futures.append((item, f))

            for item, fut in futures:
                try:
                    fut.result()
                except Exception as e:
                    self.log(f"文件 {item['name']} 抛出未捕获异常: {e}", "error")
                    self._update_item_status(item, "失败")
                    self.failed_count += 1

        speed_stop_event.set()
        self.is_uploading = False

        def _finish_ui():
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.speed_lbl.configure(text="速度: 0.0 MB/s")
            self.eta_lbl.configure(text="剩余时间: 已完成")
            self.stat_count_lbl.configure(text=f"成功: {self.completed_count} | 失败: {self.failed_count}")

            if self.stop_requested:
                self.log("⏹ 上传已按要求安全停止，支持随时继续断点续传", "warning")
            else:
                self.overall_progress_bar.set(1.0)
                self.log(f"🎉 全部上传任务结束！成功: {self.completed_count}，失败: {self.failed_count}", "success")
                if self.completed_count > 0 and self.current_folder_url:
                    if is_safe_folder_url(self.current_folder_url):
                        self.log(f"📁 专属云端网盘直达链接: {self.current_folder_url}", "cyan")
                        res = messagebox.askyesno("上传完成", "恭喜！所有素材已上传至 Google Drive 对应目录！\n\n是否立即在浏览器中打开该文件夹？")
                        if res:
                            webbrowser.open(self.current_folder_url)
                    else:
                        self.log("⚠️ 云端返回的文件夹链接未通过安全域名校验，已拦截自动打开", "warning")

        self.root_schedule(_finish_ui)

    def _upload_single_file(self, item, group, uploader, receiver, date_str, chunk_size_mb):
        if self.stop_requested:
            return

        file_path = item["path"]
        file_name = item["name"]
        file_size = item["size"]
        chunk_bytes = chunk_size_mb * 1024 * 1024

        self.log(f"[{file_name}] 正在与云端握手生成 Resumable 传输通道...", "info")
        self._update_item_status(item, "握手中...")

        # 1. 握手获取 Google Drive Resumable Upload URL
        upload_url, folder_url = self._get_upload_session(file_name, file_size, group, uploader, receiver, date_str)
        if not upload_url:
            self.log(f"[{file_name}] 获取云端免密通道失败，无法上传", "error")
            self._update_item_status(item, "失败")
            self.failed_count += 1
            return

        # 校验上传地址安全协议与域名 (防止客户端 SSRF / 任意目标写入)
        if not is_safe_upload_url(upload_url):
            self.log(f"[{file_name}] 安全拦截：云端返回的上传地址非受信任 Google 官方通道，已拒绝传输", "error")
            self._update_item_status(item, "安全拦截")
            self.failed_count += 1
            return

        item["upload_url"] = upload_url
        if folder_url and is_safe_folder_url(folder_url):
            self.current_folder_url = folder_url

        self.log(f"[{file_name}] 通道建立成功！开始分块写入 Google Drive (分块: {chunk_size_mb}MB)...", "cyan")
        self._update_item_status(item, "上传中 0%")

        # 2. Resumable 分块上传循环
        start_offset = 0
        retry_count = 0
        max_retries = 8

        try:
            with open(file_path, "rb") as f:
                while start_offset < file_size:
                    if self.stop_requested:
                        self._update_item_status(item, "已暂停", start_offset)
                        return

                    end_offset = min(start_offset + chunk_bytes, file_size) - 1
                    chunk_len = end_offset - start_offset + 1

                    f.seek(start_offset)
                    data = f.read(chunk_len)

                    headers = {
                        "Content-Length": str(chunk_len),
                        "Content-Range": f"bytes {start_offset}-{end_offset}/{file_size}"
                    }

                    # 执行分块 PUT
                    try:
                        resp = self.session.put(upload_url, headers=headers, data=data, timeout=45)
                    except (requests.exceptions.RequestException, Exception) as net_err:
                        retry_count += 1
                        if retry_count > max_retries:
                            self.log(f"[{file_name}] 网络严重中断，超过最大重试次数: {net_err}", "error")
                            self._update_item_status(item, "网络超时", start_offset)
                            self.failed_count += 1
                            return

                        # 指数退避加随机抖动避让
                        delay = min(15.0, (2 ** retry_count) + random.uniform(0.5, 2.0))
                        self.log(f"[{file_name}] 网络波动，将在 {delay:.1f} 秒后自动探针恢复断点 ({retry_count}/{max_retries})...", "warning")
                        self._update_item_status(item, f"重试中 {retry_count}", start_offset)
                        time.sleep(delay)
                        
                        # 探针查询云端已写入的字节位置
                        recovered_offset = self._query_resumable_status(upload_url, file_size)
                        if recovered_offset is not None:
                            start_offset = recovered_offset
                        continue

                    # 检查 HTTP 响应
                    if resp.status_code == 308:
                        # 308 Resume Incomplete 正常切片成功
                        range_hdr = resp.headers.get("Range", "")
                        if range_hdr and "-" in range_hdr:
                            confirmed_end = int(range_hdr.split("-")[1])
                            start_offset = confirmed_end + 1
                        else:
                            start_offset = end_offset + 1

                        pct = int((start_offset / file_size) * 100) if file_size > 0 else 100
                        self._update_item_status(item, f"上传中 {pct}%", start_offset)
                        retry_count = 0 # 成功则重置重试计数器

                    elif resp.status_code in (200, 201):
                        # 上传彻底完成
                        start_offset = file_size
                        self._update_item_status(item, "成功", file_size)
                        self.completed_count += 1
                        self.log(f"[{file_name}] 上传完成！已安全归档至云端目录 ✓", "success")
                        break

                    elif resp.status_code in (429, 500, 502, 503, 504):
                        # Google Drive 写锁冲突或限频，触发自动避让引擎
                        retry_count += 1
                        if retry_count > max_retries:
                            self.log(f"[{file_name}] 云端网盘忙碌锁死(HTTP {resp.status_code})，超过重试限制", "error")
                            self._update_item_status(item, "写锁冲突", start_offset)
                            self.failed_count += 1
                            return

                        delay = min(20.0, (2.5 ** retry_count) + random.uniform(1.0, 3.5))
                        self.log(f"[{file_name}] 触发 Google 目录并发写锁保护 (HTTP {resp.status_code})，避让休眠 {delay:.1f} 秒...", "warning")
                        self._update_item_status(item, "避让中...", start_offset)
                        time.sleep(delay)

                        recovered_offset = self._query_resumable_status(upload_url, file_size)
                        if recovered_offset is not None:
                            start_offset = recovered_offset

                    else:
                        self.log(f"[{file_name}] 云端返回异常代码 HTTP {resp.status_code}: {resp.text[:120]}", "error")
                        self._update_item_status(item, f"HTTP {resp.status_code}", start_offset)
                        self.failed_count += 1
                        return

        except Exception as e:
            self.log(f"[{file_name}] 本地读取或上传异常: {e}", "error")
            self._update_item_status(item, "本地异常")
            self.failed_count += 1

    def _query_resumable_status(self, upload_url, file_size):
        try:
            headers = {"Content-Range": f"bytes */{file_size}"}
            resp = self.session.put(upload_url, headers=headers, timeout=15)
            if resp.status_code == 308:
                range_hdr = resp.headers.get("Range", "")
                if range_hdr and "-" in range_hdr:
                    return int(range_hdr.split("-")[1]) + 1
                return 0
            elif resp.status_code in (200, 201):
                return file_size
        except Exception:
            pass
        return None

    def _get_upload_session(self, file_name, file_size, group, uploader, receiver, date_str):
        web_url = self.cfg.get("web_app_url", "").strip()
        # 清洗入参，防御注入与控制字符
        clean_file_name = sanitize_filename(file_name)
        clean_group = sanitize_text_input(group)
        clean_uploader = sanitize_text_input(uploader)
        clean_receiver = sanitize_text_input(receiver)

        payload = {
            "action": "prepareUploadSession",
            "fileName": clean_file_name,
            "fileSize": file_size,
            "mimeType": "application/octet-stream",
            "group": clean_group,
            "groupName": clean_group,
            "uploader": clean_uploader,
            "uploaderName": clean_uploader,
            "admin": clean_receiver,
            "adminName": clean_receiver,
            "receiver": clean_receiver,
            "receiverName": clean_receiver,
            "dateStr": date_str
        }

        # 代理设置与协议安全校验
        proxies = {}
        if self.cfg.get("proxy_url"):
            is_valid, cleaned_proxy = validate_proxy_url(self.cfg.get("proxy_url"))
            if is_valid and cleaned_proxy:
                proxies = {"http": cleaned_proxy, "https": cleaned_proxy}

        def _extract(res):
            if not isinstance(res, dict):
                return None, None
            d = res.get("data") if isinstance(res.get("data"), dict) else {}
            u = res.get("uploadUrl") or d.get("uploadUrl") or res.get("url") or d.get("url")
            f = res.get("folderUrl") or d.get("folderUrl") or res.get("folder_url") or d.get("folder_url") or ""
            return u, f

        for attempt in range(1, 5):
            if self.stop_requested:
                return None, None
            try:
                # 1. 优先使用 POST 发送 JSON 请求
                resp = self.session.post(web_url, json=payload, proxies=proxies, timeout=25)
                if resp.status_code == 200:
                    try:
                        res_data = resp.json()
                        u, f = _extract(res_data)
                        if u:
                            return u, f
                        else:
                            err_msg = res_data.get("message") or res_data.get("error") or (res_data.get("data", {}).get("message") if isinstance(res_data.get("data"), dict) else "") or "服务端未知响应"
                            self.log(f"[{file_name}] 云端通道握手提示: {str(err_msg)[:100]}", "warning")
                    except Exception:
                        self.log(f"[{file_name}] POST响应解析失败 (HTTP 200 非合法JSON)", "warning")
                
                # 2. 备选 GET 参数 (使用 params 字典安全编码，杜绝 URL 拼接注入)
                resp2 = self.session.get(web_url, params=payload, proxies=proxies, timeout=25)
                if resp2.status_code == 200:
                    try:
                        res_data2 = resp2.json()
                        u, f = _extract(res_data2)
                        if u:
                            return u, f
                    except Exception:
                        pass

            except Exception as e:
                self.log(f"[{file_name}] 握手连接尝试 {attempt} 发生网络抖动: {type(e).__name__}", "warning")

            time.sleep(1.2 * attempt)

        return None, None

    def _monitor_speed_thread(self, stop_event):
        last_time = time.time()
        last_bytes = 0

        while not stop_event.is_set():
            time.sleep(1.0)
            now = time.time()
            elapsed = now - last_time
            if elapsed <= 0:
                continue

            current_uploaded = sum(it.get("uploaded_bytes", 0) for it in self.files_queue)
            diff = current_uploaded - last_bytes
            speed = diff / elapsed if diff >= 0 else 0

            last_time = now
            last_bytes = current_uploaded

            # 计算剩余时间
            remaining_bytes = max(0, self.total_bytes - current_uploaded)
            eta_seconds = (remaining_bytes / speed) if speed > 1024 else None

            # 整体进度比例
            overall_ratio = (current_uploaded / self.total_bytes) if self.total_bytes > 0 else 0

            def _update_ui(c_up=current_uploaded, sp=speed, eta=eta_seconds, ratio=overall_ratio):
                self.overall_progress_bar.set(ratio)
                self.speed_lbl.configure(text=f"速度: {format_speed(sp)}")
                self.eta_lbl.configure(text=f"剩余时间: {format_seconds(eta)}")
                self.stat_count_lbl.configure(text=f"成功: {self.completed_count} | 失败: {self.failed_count}")
                self.footer_left.configure(text=f"传输进度: {format_size(c_up)} / {format_size(self.total_bytes)} ({(ratio*100):.1f}%)")

            self.root_schedule(_update_ui)

    def _open_current_folder(self):
        if self.current_folder_url and is_safe_folder_url(self.current_folder_url):
            webbrowser.open(self.current_folder_url)
        elif self.current_folder_url:
            messagebox.showwarning("安全警告", "云端链接格式未通过安全校验，已拦截自动打开！")
        else:
            messagebox.showinfo("提示", "当前尚未创建或上传至云端文件夹，请开始上传后即可一键打开！")

    # ---------------- 弹窗与设置对话框 ----------------
    def _test_connection_async(self):
        self.log("🌐 正在测试与 Google Apps Script 及 Google Drive 的握手延迟...", "cyan")
        def _worker():
            url = self.cfg.get("web_app_url", "").strip()
            if not url:
                self.log("❌ 未配置脚本网址，请进入【⚙ 全局设置】配置", "error")
                return
            t0 = time.time()
            proxies = {}
            if self.cfg.get("proxy_url"):
                is_valid, cleaned_proxy = validate_proxy_url(self.cfg.get("proxy_url"))
                if is_valid and cleaned_proxy:
                    proxies = {"http": cleaned_proxy, "https": cleaned_proxy}
            try:
                r = requests.get(url, proxies=proxies, timeout=12)
                cost = int((time.time() - t0) * 1000)
                if r.status_code == 200:
                    self.log(f"✓ 握手成功！HTTP 200 OK · 云端延迟: {cost} ms · 专线通道畅通", "success")
                    self.root_schedule(lambda: self.ready_badge.configure(text="云端畅通", fg_color="#064e3b", text_color="#34d399"))
                else:
                    self.log(f"⚠️ 云端返回状态异常: HTTP {r.status_code} ({cost} ms)", "warning")
            except Exception as e:
                self.log(f"❌ 连接失败: {type(e).__name__}，请检查系统 VPN/代理 是否正常开启", "error")
                self.root_schedule(lambda: self.ready_badge.configure(text="连接中断", fg_color="#7f1d1d", text_color="#f87171"))
        threading.Thread(target=_worker, daemon=True).start()

    def _show_settings_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("⚙ 全局设置 - 云端与网络参数")
        dlg.geometry("540x380")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(fg_color="#0e1522")

        ctk.CTkLabel(dlg, text="全局设置与 Google 云端连接", font=ctk.CTkFont(size=14, weight="bold"), text_color="#ffffff").pack(anchor="w", padx=20, pady=(16, 6))

        box = ctk.CTkFrame(dlg, fg_color="#141c2c", border_color="#1e2c44", border_width=1, corner_radius=8)
        box.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        # 1. 脚本网址
        ctk.CTkLabel(box, text="Google Apps Script 部署网址 (Web App URL):", font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold"), text_color="#94a3b8").pack(anchor="w", padx=14, pady=(12, 2))
        url_ent = ctk.CTkEntry(box, fg_color="#0e1522", border_color="#24344d", font=ctk.CTkFont(family="Microsoft YaHei", size=11), height=30)
        url_ent.insert(0, self.cfg.get("web_app_url", ""))
        url_ent.pack(fill="x", padx=14, pady=(0, 10))

        # 2. 并发与切片大小
        row1 = ctk.CTkFrame(box, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(0, 10))
        row1.columnconfigure(0, weight=1)
        row1.columnconfigure(1, weight=1)

        c1 = ctk.CTkFrame(row1, fg_color="transparent")
        c1.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(c1, text="并发上传线程数 (推荐 2 线程):", font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold"), text_color="#94a3b8").pack(anchor="w", pady=(0, 2))
        concurrency_opt = ctk.CTkOptionMenu(c1, values=["1", "2", "3", "4"], fg_color="#1c283e", button_color="#273854", height=30)
        concurrency_opt.set(str(self.cfg.get("concurrency", 2)))
        concurrency_opt.pack(fill="x")

        c2 = ctk.CTkFrame(row1, fg_color="transparent")
        c2.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ctk.CTkLabel(c2, text="切片分块大小 (Chunk Size):", font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold"), text_color="#94a3b8").pack(anchor="w", pady=(0, 2))
        chunk_opt = ctk.CTkOptionMenu(c2, values=["2 MB", "4 MB", "8 MB", "16 MB"], fg_color="#1c283e", button_color="#273854", height=30)
        cur_ck = f"{self.cfg.get('chunk_size_mb', 4)} MB"
        chunk_opt.set(cur_ck if cur_ck in ["2 MB", "4 MB", "8 MB", "16 MB"] else "4 MB")
        chunk_opt.pack(fill="x")

        # 3. 本地代理 (可选)
        ctk.CTkLabel(box, text="本地网络代理 (可选，如 http://127.0.0.1:7890):", font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold"), text_color="#94a3b8").pack(anchor="w", padx=14, pady=(4, 2))
        proxy_ent = ctk.CTkEntry(box, placeholder_text="不填则使用系统默认网卡/VPN", fg_color="#0e1522", border_color="#24344d", font=ctk.CTkFont(family="Microsoft YaHei", size=11), height=30)
        proxy_ent.insert(0, self.cfg.get("proxy_url", ""))
        proxy_ent.pack(fill="x", padx=14, pady=(0, 10))

        # 底部按钮
        btn_box = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_box.pack(fill="x", padx=20, pady=(0, 16))

        def _save():
            new_url = url_ent.get().strip()
            if new_url and not (new_url.startswith("https://script.google.com/") or new_url.startswith("https://")):
                messagebox.showerror("格式错误", "Google Apps Script 网址必须以 https:// 开头！")
                return

            new_proxy = proxy_ent.get().strip()
            is_valid, msg_or_proxy = validate_proxy_url(new_proxy)
            if not is_valid:
                messagebox.showerror("代理设置错误", msg_or_proxy)
                return

            self.cfg["web_app_url"] = new_url
            self.cfg["concurrency"] = int(concurrency_opt.get())
            self.cfg["chunk_size_mb"] = int(chunk_opt.get().split()[0])
            self.cfg["proxy_url"] = msg_or_proxy
            save_config(self.cfg)
            self.concurrency_badge.configure(text=f"⚡ 并发: {self.cfg['concurrency']} 线程")
            self._check_config_status()
            dlg.destroy()
            messagebox.showinfo("成功", "全局设置已成功保存！")

        save_btn = ctk.CTkButton(btn_box, text="保存设置", fg_color="#1877f2", hover_color="#166fe5", text_color="#ffffff", width=90, height=32, font=ctk.CTkFont(family="Microsoft YaHei", size=11, weight="bold"), command=_save)
        save_btn.pack(side="right", padx=(8, 0))

        cancel_btn = ctk.CTkButton(btn_box, text="取消", fg_color="#1c283e", hover_color="#293955", text_color="#cbd5e1", width=70, height=32, font=ctk.CTkFont(family="Microsoft YaHei", size=11), command=dlg.destroy)
        cancel_btn.pack(side="right")

    def _show_help_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("❓ 使用说明与目录规则")
        dlg.geometry("620x460")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(fg_color="#0e1522")

        ctk.CTkLabel(dlg, text="云端文件极速上传器 使用指南", font=ctk.CTkFont(size=14, weight="bold"), text_color="#ffffff").pack(anchor="w", padx=20, pady=(16, 8))

        help_box = ctk.CTkScrollableFrame(dlg, fg_color="#141c2c", border_color="#1e2c44", border_width=1, corner_radius=8)
        help_box.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        help_text = """
1. 目录归档层级规则：
   素材将严格根据您选择的分类，在 Google Drive 云端自动创建并归档至以下五级路径：
   【根目录】➔【所选分组】➔【你的名字】➔【当天日期 (yyyy-MM-dd)】➔【接收人/新人名字】➔【文件】

2. 四大业务部门分组：
   • 视频组 / 效果组 / 作图组：
     第三项请填写【接收文件的人/管理员名字】（如：组长、李四等）。
   • 新人拍摄素材：
     第三项系统将自动切换为【新人的名字+尾号后4位】（如：王五1234）。

3. 多人频繁上传与写锁防冲突避让引擎：
   • 针对同一时间多人向同一个文件夹并发上传时出现的 Google Drive 文件夹写锁限制（HTTP 429 / 500 / 503），本客户端内置智能 Jitter 指数退避算法。
   • 软件会自动微调上传间歇，彻底避免文件写入同一目录时发生锁定冲突或漏传至根目录。

4. 5TB 超大素材与断点续传：
   • 采用 Google Drive 官方 API v3 Resumable 分块流式协议。
   • 即使遭遇 VPN 切换或网络波动，软件会自动重新对齐切片偏移，无需重新从 0 开始。
"""
        lbl = ctk.CTkLabel(help_box, text=help_text.strip(), justify="left", font=ctk.CTkFont(family="Microsoft YaHei", size=11), text_color="#cbd5e1")
        lbl.pack(anchor="w", padx=10, pady=10)

    def _show_path_preview(self):
        group = self.group_var.get()
        uploader = self.uploader_entry.get().strip() or "你的名字"
        receiver = self.receiver_entry.get().strip() or ("新人名字+尾号" if group == "新人拍摄素材" else "接收人姓名")
        date_str = datetime.now().strftime("%Y-%m-%d")

        full_path = f"Google Drive 根目录\n  └── {group}\n        └── {uploader}\n              └── {date_str}\n                    └── {receiver}\n                          └── [上传的所有素材文件]"
        messagebox.showinfo("当前上传目录预览", f"当前所选参数将对应的云端存储路径：\n\n{full_path}")

    def _switch_tab_queue(self):
        # 激活队列明细视窗提示
        count = len(self.files_queue)
        messagebox.showinfo("传输队列", f"当前队列共有 {count} 个文件。\n可直接在右侧窗口查看切片进度与状态！")

if __name__ == "__main__":
    app = ModernUploaderApp()
    app.mainloop()
