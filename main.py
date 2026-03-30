
import tkinter as tk
import json
from tkinter import messagebox
from pathlib import Path
import ttkbootstrap as tb
from ttkbootstrap.constants import *

from watermark_module import WatermarkModule
from split_module import SplitModule
from merge_module import MergeModule
from resize_module import ResizeModule
from compress_module import CompressModule
from common_utils import load_app_settings, save_app_settings, load_module_presets, preset_file, write_json, open_in_explorer
from exif_module import ExifModule
from convert_module import ConvertModule
from rename_module import RenameModule
from crop_module import CropModule
from transform_module import TransformModule
from dedupe_module import DedupeModule
from compare_module import CompareModule
from queue_module import QueueModule
from retouch_module import RetouchModule
from ai_watermark_remove_module import AIWatermarkRemoveModule

APP_NAME = "图片处理工具箱"
APP_VERSION = "v2.1"
APP_AUTHOR = "Kurt"
APP_ICON = "app_icon.ico"
APP_BASE_DIR = Path(__file__).resolve().parent
APP_ICON_PATH = str(APP_BASE_DIR / APP_ICON)


def _install_ttkbootstrap_compat():
    original_labelframe = tb.LabelFrame

    class CompatLabelFrame(original_labelframe):
        def __init__(self, *args, **kwargs):
            try:
                super().__init__(*args, **kwargs)
            except tk.TclError as e:
                if 'unknown option "-padding"' in str(e):
                    kwargs.pop("padding", None)
                    super().__init__(*args, **kwargs)
                else:
                    raise
    tb.LabelFrame = CompatLabelFrame

_install_ttkbootstrap_compat()



def draw_brand_logo(canvas, size=86, accent="#0d6efd"):
    canvas.delete("all")
    canvas.configure(bg="#ffffff")
    pad = 5
    canvas.create_oval(pad, pad, size-pad, size-pad, fill=accent, outline="")
    canvas.create_text(size//2, size//2 - 6, text="K", fill="white", font=("Arial", max(18, size//3), "bold"))
    canvas.create_text(size//2, size//2 + 18, text="IMAGE", fill="#dbeafe", font=("Arial", max(7, size//12), "bold"))

def make_brand_header(parent, title, subtitle="", badge_text="Kurt Brand"):
    top = tb.Frame(parent)
    top.pack(fill=X, pady=(0, 14))
    logo = tk.Canvas(top, width=78, height=78, highlightthickness=0, bg="#ffffff")
    logo.pack(side=LEFT, padx=(0, 14))
    draw_brand_logo(logo, size=78)

    titles = tb.Frame(top)
    titles.pack(side=LEFT, fill=BOTH, expand=YES)
    tb.Label(titles, text=title, font=("微软雅黑", 18, "bold")).pack(anchor=W)
    if subtitle:
        tb.Label(titles, text=subtitle, bootstyle="secondary").pack(anchor=W, pady=(4, 0))
    tb.Label(titles, text=badge_text, bootstyle="info").pack(anchor=W, pady=(8, 0))
    return top


def draw_small_brand_icon(canvas, label, accent="#0d6efd"):
    canvas.delete("all")
    canvas.configure(bg="#ffffff")
    canvas.create_rounded_rect = None
    canvas.create_rectangle(4, 4, 40, 40, outline="", fill=accent)
    canvas.create_text(22, 22, text=label, fill="white", font=("Arial", 12, "bold"))


MODULE_ICON_MAP = {
    "水印": "水",
    "切分": "切",
    "拼接": "拼",
    "分辨率": "尺",
    "压缩": "压",
    "EXIF": "E",
    "格式转换": "转",
    "重命名": "名",
    "裁剪": "裁",
    "旋转/边框": "边",
    "去重": "重",
    "对比": "比",
    "普通修复": "修",
    "任务队列": "队",
}

def draw_module_badge(canvas, module_name, active=False):
    canvas.delete("all")
    bg = "#0d6efd" if active else "#9ec5fe"
    fg = "white" if active else "#0b3d91"
    label = MODULE_ICON_MAP.get(module_name, module_name[:1] if module_name else "?")
    canvas.configure(bg="#ffffff")
    canvas.create_oval(4, 4, 36, 36, fill=bg, outline="")
    canvas.create_text(20, 20, text=label, fill=fg, font=("Arial", 11, "bold"))





class SplashScreen(tb.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.overrideredirect(True)
        self.geometry("560x320")
        self.attributes("-topmost", True)
        try:
            self.iconbitmap(APP_ICON_PATH)
        except Exception:
            pass

        frame = tb.Frame(self, padding=26)
        frame.pack(fill=BOTH, expand=YES)

        hero = tb.LabelFrame(frame, text="图片工具箱")
        hero.pack(fill=BOTH, expand=YES)
        hero_inner = tb.Frame(hero, padding=22)
        hero_inner.pack(fill=BOTH, expand=YES)

        head = make_brand_header(hero_inner, APP_NAME, f"{APP_VERSION} · 专业图片工作台", f"By {APP_AUTHOR}")
        tb.Label(hero_inner, text="正在加载界面、模块与预览系统...", bootstyle="secondary").pack(anchor=W, pady=(6, 0))

        bar = tb.Progressbar(hero_inner, mode="indeterminate", bootstyle="primary-striped", length=360)
        bar.pack(anchor=W, pady=(20, 0))
        bar.start(12)

        foot = tb.Frame(hero_inner)
        foot.pack(fill=X, pady=(18, 0))
        tb.Label(foot, text="Image Tool Brand Experience", bootstyle="secondary").pack(side=LEFT)
        tb.Label(foot, text="K", bootstyle="info").pack(side=RIGHT)

        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - 280
        y = (self.winfo_screenheight() // 2) - 160
        self.geometry(f"560x320+{x}+{y}")




class TemplateManagerDialog(tb.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("模板管理中心")
        self.geometry("980x750")
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)
        try:
            self.iconbitmap(APP_ICON_PATH)
        except Exception:
            pass
        self.minsize(760, 750)

        wrap = tb.Frame(self, padding=18)
        wrap.pack(fill=BOTH, expand=YES)

        hero = tb.LabelFrame(wrap, text="管理说明")
        hero.pack(fill=X, pady=(0, 12))
        hero_inner = tb.Frame(hero, padding=12)
        hero_inner.pack(fill=X)
        tb.Label(hero_inner, text="左侧选择模块，右侧查看该模块下已保存的模板。", bootstyle="secondary").pack(anchor=W)

        body = tb.Frame(wrap)
        body.pack(fill=BOTH, expand=YES)

        left = tb.LabelFrame(body, text="模块列表")
        left.pack(side=LEFT, fill=Y, padx=(0, 12))
        li = tb.Frame(left, padding=12)
        li.pack(fill=BOTH, expand=YES)
        self.module_list = tk.Listbox(li, width=20, exportselection=False)
        self.module_list.pack(fill=BOTH, expand=YES)
        self.module_list.bind("<<ListboxSelect>>", self.refresh_presets)
        self.modules = ['水印','切分','拼接','分辨率','压缩','EXIF','格式转换','重命名','裁剪','旋转/边框']
        self.module_key_map = {'水印':'watermark','切分':'split','拼接':'merge','分辨率':'resize','压缩':'compress','EXIF':'exif','格式转换':'convert','重命名':'rename','裁剪':'crop','旋转/边框':'transform'}
        for m in self.modules:
            self.module_list.insert('end', m)

        right = tb.LabelFrame(body, text="模板列表")
        right.pack(side=LEFT, fill=BOTH, expand=YES)
        ri = tb.Frame(right, padding=12)
        ri.pack(fill=BOTH, expand=YES)

        self.preset_info = tb.Label(ri, text="请选择左侧模块后查看模板。", bootstyle="secondary")
        self.preset_info.pack(anchor=W, pady=(0, 8))

        self.preset_list = tk.Listbox(ri, exportselection=False, height=18)
        self.preset_list.pack(fill=BOTH, expand=YES)

        foot = tb.Frame(wrap)
        foot.pack(fill=X, pady=(12, 0))
        tb.Separator(foot, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))
        btnrow = tb.Frame(foot)
        btnrow.pack(fill=X)
        tb.Label(btnrow, text="模板与模块均已采用统一风格。", bootstyle="secondary").pack(side=LEFT)
        tb.Button(btnrow, text="删除选中模板", bootstyle="danger-outline", command=self.delete_selected, width=16).pack(side=RIGHT)
        tb.Button(btnrow, text="关闭窗口", bootstyle="secondary-outline", command=self.destroy, width=16).pack(side=RIGHT, padx=8)

        if self.modules:
            self.module_list.selection_set(0)
            self.refresh_presets()

    def current_module(self):
        sel = self.module_list.curselection()
        return self.modules[sel[0]] if sel else None

    def refresh_presets(self, _event=None):
        module = self.current_module()
        self.preset_list.delete(0, 'end')
        if not module:
            self.preset_info.configure(text="请选择左侧模块后查看模板。")
            return
        presets = load_module_presets(self.module_key_map.get(module, module))
        self.preset_info.configure(text=f"当前模块：{module}  |  模板数量：{len(presets)}")
        for idx, p in enumerate(presets, 1):
            self.preset_list.insert('end', p.get('preset_name') or f'模板{idx}')

    def delete_selected(self):
        module = self.current_module()
        sel = self.preset_list.curselection()
        if not module or not sel:
            return
        presets = load_module_presets(self.module_key_map.get(module, module))
        del presets[sel[0]]
        write_json(preset_file(module), presets)
        self.refresh_presets()



class SettingsDialog(tb.Toplevel):
    def __init__(self, master, style, save_callback, load_callback, current_settings):
        super().__init__(master)
        self.style_obj = style
        self.save_callback = save_callback
        self.load_callback = load_callback
        self.current_settings = current_settings
        self.title("设置中心")
        self.geometry("850x600")
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)
        try:
            self.iconbitmap(APP_ICON_PATH)
        except Exception:
            pass

        wrap = tb.Frame(self, padding=18)
        wrap.pack(fill=BOTH, expand=YES)
        self.minsize(850, 600)

        appearance = tb.LabelFrame(wrap, text="界面设置")
        appearance.pack(fill=X, pady=(0, 12))
        inner = tb.Frame(appearance, padding=12)
        inner.pack(fill=X)
        
        self.theme_display_map = {
            "flatly": "☀  扁平浅色",
            "darkly": "🌙 深色模式",
            "cosmo": "🎨 宇宙浅色",
            "minty": "🌿 薄荷清新",
            "litera": "📖 阅读模式",
            "journal": "📰 报刊风格"
        }
        self.theme_reverse_map = {v: k for k, v in self.theme_display_map.items()}
        
        current_theme = self.style_obj.theme_use()
        current_display = self.theme_display_map.get(current_theme, "☀  扁平浅色")
        self.theme_var = tk.StringVar(value=current_display)
        
        tb.Label(inner, text="界面主题:", width=12, anchor=W).pack(side=LEFT, padx=(0, 8))
        theme_box = tb.Combobox(inner, textvariable=self.theme_var, state="readonly", width=18,
                                values=list(self.theme_display_map.values()))
        theme_box.pack(side=LEFT)
        theme_box.bind("<<ComboboxSelected>>", self.on_auto_save)

        behavior = tb.LabelFrame(wrap, text="全局行为")
        behavior.pack(fill=X, pady=(0, 12))
        b = tb.Frame(behavior, padding=12)
        b.pack(fill=X)
        self.remember_theme = tk.BooleanVar(value=self.current_settings.get("remember_theme", True))
        self.auto_open_output = tk.BooleanVar(value=self.current_settings.get("auto_open_output", True))
        tb.Checkbutton(b, text="记住主题选择", variable=self.remember_theme, bootstyle="round-toggle", command=self.on_auto_save).pack(anchor=W)
        tb.Checkbutton(b, text="完成后自动打开输出文件夹", variable=self.auto_open_output, bootstyle="round-toggle", command=self.on_auto_save).pack(anchor=W, pady=(8,0))

        preset = tb.LabelFrame(wrap, text="模板与工作流")
        preset.pack(fill=BOTH, expand=YES)
        p = tb.Frame(preset, padding=12)
        p.pack(fill=BOTH, expand=YES)
        tb.Label(p, text="所有功能模块都支持模板保存和加载。", justify=LEFT).pack(anchor=W)
        tb.Label(p, text="您可以保存多个模板，使用时从列表中选择。也可在模板管理中心统一管理所有模板。", justify=LEFT, bootstyle="secondary", wraplength=760).pack(anchor=W, pady=(10,0))
        tb.Button(p, text="打开模板管理", bootstyle="info-outline", command=self.open_template_manager, width=16).pack(anchor=W, pady=(12,0))

        foot = tb.Frame(wrap)
        foot.pack(side=BOTTOM, fill=X, pady=(12, 0))
        tb.Separator(foot, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))
        btnrow = tb.Frame(foot)
        btnrow.pack(fill=X)
        tb.Label(btnrow, text="设置已自动保存", bootstyle="secondary").pack(side=LEFT)
        tb.Button(btnrow, text="关闭", bootstyle="secondary-outline", command=self.destroy, width=16).pack(side=RIGHT)

    def open_template_manager(self):
        TemplateManagerDialog(self)

    def on_auto_save(self, event=None):
        try:
            selected_display = self.theme_var.get()
            theme_name = self.theme_reverse_map.get(selected_display, "cosmo")
            
            self.style_obj.theme_use(theme_name)
            self.current_settings["remember_theme"] = self.remember_theme.get()
            self.current_settings["auto_open_output"] = self.auto_open_output.get()
            self.current_settings["theme"] = theme_name
            self.save_callback()
        except Exception as e:
            messagebox.showerror("错误", f"保存设置失败：{e}")



class AboutDialog(tb.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title(f"关于我们 - {APP_NAME}")
        self.geometry("840x660")
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)
        try:
            self.iconbitmap(APP_ICON_PATH)
        except Exception:
            pass
        self.minsize(760, 520)

        wrap = tb.Frame(self, padding=22)
        wrap.pack(fill=BOTH, expand=YES)
        make_brand_header(wrap, APP_NAME, f"{APP_VERSION} · 专业图片工作台", f"By {APP_AUTHOR}")

        hero = tb.LabelFrame(wrap, text="软件简介")
        hero.pack(fill=X, pady=(0, 14))
        hero_in = tb.Frame(hero, padding=16)
        hero_in.pack(fill=X)
        tb.Label(hero_in, text="这是一套面向批量图片处理与桌面工作流的 GUI 工具。", justify=LEFT, wraplength=680).pack(anchor=W)
        tb.Label(hero_in, text="涵盖水印、切分、拼接、分辨率修改、压缩、格式转换、EXIF处理、裁剪、旋转翻转、边框背景、去重、对比、普通修复与任务队列。", justify=LEFT, wraplength=680, bootstyle="secondary").pack(anchor=W, pady=(10, 0))

        info = tb.Frame(wrap)
        info.pack(fill=BOTH, expand=YES, pady=(0, 14))
        left = tb.LabelFrame(info, text="核心能力")
        left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 8))
        left_in = tb.Frame(left, padding=14)
        left_in.pack(fill=BOTH, expand=YES)
        for t in [
            "时间戳 / 文字水印 + 模板",
            "随机切分与批量方案",
            "格式转换 / EXIF清理 / 批量重命名",
            "旋转 / 翻转 / 加边框 / 加背景",
            "相似图去重 / 图片对比 / 普通修复",
            "任务队列 / 模板管理 / 设置中心",
        ]:
            tb.Label(left_in, text="• " + t).pack(anchor=W, pady=2)

        foot = tb.Frame(wrap)
        foot.pack(fill=X)
        tb.Separator(foot, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))
        btnrow = tb.Frame(foot)
        btnrow.pack(fill=X)
        tb.Label(btnrow, text="Image Tool · Brand Edition", bootstyle="secondary").pack(side=LEFT)
        tb.Button(btnrow, text="关闭窗口", bootstyle="secondary-outline", command=self.destroy, width=16).pack(side=RIGHT)


class ImageToolApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION} - By {APP_AUTHOR}")
        self.root.geometry("1600x1080")
        self.root.minsize(1280, 820)
        try:
            self.root.iconbitmap(APP_ICON_PATH)
        except Exception:
            pass

        self.settings = self._load_settings()
        self.remember_theme = self.settings.get("remember_theme", True)
        self.auto_open_output = self.settings.get("auto_open_output", True)
        self.style = tb.Style(theme=self.settings.get("theme", "cosmo"))
        self.build_ui()


    def _load_settings(self):
        return load_app_settings()

    def _save_settings(self):
        self.remember_theme = self.settings.get("remember_theme", getattr(self, "remember_theme", True))
        self.auto_open_output = self.settings.get("auto_open_output", getattr(self, "auto_open_output", True))
        settings = {
            "theme": self.settings.get("theme", self.style.theme_use()),
            "remember_theme": self.remember_theme,
            "auto_open_output": self.auto_open_output,
        }
        self.settings.update(settings)
        save_app_settings(settings)



    def apply_card_style(self, widget):
        try:
            widget.configure(bootstyle="light")
        except Exception:
            pass

    def section_title(self, parent, text, subtext=""):
        wrap = tb.Frame(parent)
        wrap.pack(fill=X, pady=(0, 8))
        tb.Label(wrap, text=text, font=("微软雅黑", 12, "bold")).pack(anchor=W)
        if subtext:
            tb.Label(wrap, text=subtext, bootstyle="secondary").pack(anchor=W, pady=(2, 0))
        return wrap





    def build_ui(self):
        outer = tb.Frame(self.root)
        outer.pack(fill=BOTH, expand=YES)

        main_area = tb.Frame(outer)
        main_area.pack(fill=BOTH, expand=YES, padx=10, pady=10)

        toolbar = tb.LabelFrame(main_area, text="快捷操作")
        toolbar.pack(fill=X, pady=(0, 8))
        toolbar_inner = tb.Frame(toolbar, padding=12)
        toolbar_inner.pack(fill=X, expand=YES)
        for col in range(5):
            toolbar_inner.grid_columnconfigure(col, weight=1)

        tb.Button(toolbar_inner, text="⚙ 设置中心", bootstyle="secondary-outline", command=self.show_settings, width=16).grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        tb.Button(toolbar_inner, text="🗂 模板管理", bootstyle="info-outline", command=lambda: TemplateManagerDialog(self.root), width=16).grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        tb.Button(toolbar_inner, text="☀ 浅色主题", bootstyle="secondary-outline", command=lambda: self.set_theme("flatly"), width=16).grid(row=0, column=2, padx=4, pady=4, sticky="ew")
        tb.Button(toolbar_inner, text="☾ 深色主题", bootstyle="secondary-outline", command=lambda: self.set_theme("darkly"), width=16).grid(row=0, column=3, padx=4, pady=4, sticky="ew")
        tb.Button(toolbar_inner, text="ⓘ 关于我们", bootstyle="secondary-outline", command=self.show_about, width=16).grid(row=0, column=4, padx=4, pady=4, sticky="ew")

        notebook_wrap = tb.LabelFrame(main_area, text="模块工作区")
        notebook_wrap.pack(fill=BOTH, expand=YES, pady=(0, 8))
        notebook_inner = tb.Frame(notebook_wrap, padding=8)
        notebook_inner.pack(fill=BOTH, expand=YES)

        self.notebook = tb.Notebook(notebook_inner, bootstyle="primary")
        self.notebook.pack(fill=BOTH, expand=YES)

        self.modules = {}
        self.module_order = ["水印","切分","拼接","分辨率","压缩","EXIF","格式转换","重命名","裁剪","旋转/边框","去重","对比","普通修复","任务队列"]
        tabs = [
            ("▣ 水印", WatermarkModule),
            ("✂ 切分", SplitModule),
            ("▤ 拼接", MergeModule),
            ("◫ 分辨率", ResizeModule),
            ("◩ 压缩", CompressModule),
            ("◎ EXIF", ExifModule),
            ("⇄ 格式转换", ConvertModule),
            ("✎ 重命名", RenameModule),
            ("⌗ 裁剪", CropModule),
            ("⟳ 旋转/边框", TransformModule),
            ("◌ 去重", DedupeModule),
            ("≋ 对比", CompareModule),
            ("✦ 普通修复", RetouchModule),
            ("✧ AI去水印", AIWatermarkRemoveModule),
            ("☰ 任务队列", QueueModule),
        ]
        for label, cls in tabs:
            frame = tb.Frame(self.notebook, padding=12)
            self.notebook.add(frame, text=f"  {label}  ")
            plain_label = label.split(" ", 1)[1] if " " in label else label
            self.modules[plain_label] = cls(
                frame,
                self.create_progress_window,
                self.update_progress,
                self.finish_processing
            )

        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        status = tb.Frame(main_area, padding=(12, 6))
        status.pack(fill=X)
        tb.Separator(status, orient=HORIZONTAL).pack(fill=X, pady=(0, 6))
        self.status_text = tb.Label(status, text="就绪", bootstyle="secondary")
        self.status_text.pack(side=LEFT)
        self.status_right = tb.Label(status, text="标签页 · 深色预览区 · 统一工具栏样式", bootstyle="secondary")
        self.status_right.pack(side=RIGHT)


    def set_theme(self, theme_name):
        try:
            self.style.theme_use(theme_name)
            self._save_settings()
            self.status_text.configure(text=f"已切换主题：{theme_name}")
        except Exception as e:
            messagebox.showerror("错误", f"切换主题失败：{e}")



    def select_module_by_name(self, module_name):
        try:
            idx = self.module_order.index(module_name)
            self.notebook.select(idx)
        except Exception:
            pass

    def update_nav_highlight(self, active_module):
        return

    def on_tab_changed(self, event=None):
        try:
            idx = self.notebook.index(self.notebook.select())
            text = self.notebook.tab(idx, "text").strip()
            text = text.split(" ", 1)[1] if " " in text else text
            hints = {
                "水印": "支持时间戳 / 文字水印与模板快速载入。",
                "切分": "支持随机切分、批量方案和结果独立文件夹。",
                "拼接": "支持目录拼接、背景色与顺序控制。",
                "分辨率": "支持单图/文件夹调整和实时预览。",
                "压缩": "支持目标体积、失败重试与缩分辨率。",
                "EXIF": "支持查看与清理图片元数据。",
                "格式转换": "支持 JPG / PNG / WEBP 批量转换。",
                "重命名": "支持前缀、编号位数和复制/就地改名。",
                "裁剪": "支持比例裁剪与像素裁剪。",
                "旋转/边框": "支持旋转、翻转、边框与背景增强。",
                "去重": "支持相似图检测、勾选处理与统一卡片式操作区。",
                "对比": "支持两图差异对比、差异图导出与统一卡片式操作区。",
                "普通修复": "支持局部修复、橡皮擦、历史面板、分屏对比和保存前确认。",
                "任务队列": "支持多任务顺序处理、模板工作流与统一卡片式管理区。",
            }
            self.status_text.configure(text=f"当前模块：{text}")
        except Exception:
            pass

    def create_progress_window(self, title, total):
        win = tb.Toplevel(self.root)
        win.title("处理进度")
        win.geometry("640x240")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        try:
            win.iconbitmap(APP_ICON_PATH)
        except Exception:
            pass

        win.update_idletasks()
        x = (win.winfo_screenwidth() // 2) - (640 // 2)
        y = (win.winfo_screenheight() // 2) - (240 // 2)
        win.geometry(f"640x240+{x}+{y}")

        wrap = tb.Frame(win, padding=22)
        wrap.pack(fill=BOTH, expand=YES)

        tb.Label(wrap, text=title, font=("微软雅黑", 14, "bold")).pack(anchor=W, pady=(0, 14))
        progress = tb.Progressbar(wrap, maximum=max(1,total), mode="determinate", bootstyle="success-striped")
        progress.pack(fill=X, pady=(0, 14))
        current = tb.Label(wrap, text="准备中...", wraplength=580, justify=LEFT, bootstyle="secondary")
        current.pack(anchor=W)

        foot = tb.Frame(wrap)
        foot.pack(fill=X, pady=(18, 0))
        percent = tb.Label(foot, text="0%", font=("微软雅黑", 12, "bold"), bootstyle="info")
        percent.pack(side=LEFT)
        tb.Label(foot, text="处理中请勿关闭窗口", bootstyle="secondary").pack(side=RIGHT)

        win.progress_bar = progress
        win.current_file_label = current
        win.status_label = percent
        return win

    def update_progress(self, progress_window, current, total, current_file):
        total = max(total, 1)
        progress_window.progress_bar["value"] = current + 1
        percentage = int((current + 1) / total * 100)
        progress_window.status_label.configure(text=f"{percentage}%")
        progress_window.current_file_label.configure(text=f"正在处理：{current_file}")
        progress_window.update()
        self.status_text.configure(text=f"处理中：{current_file}")

    def finish_processing(self, progress_window, processed, failed, task_name, extra_info=""):
        progress_window.progress_bar["value"] = progress_window.progress_bar["maximum"]
        progress_window.status_label.configure(text="100%")
        progress_window.current_file_label.configure(text="所有任务已完成")
        progress_window.update()
        self.root.after(350, progress_window.destroy)
        self.status_text.configure(text=f"{task_name}已完成")

        msg = f"{task_name}完成\n\n成功：{processed} 个\n失败：{len(failed)} 个"
        if extra_info:
            msg += f"\n\n{extra_info}"
        if failed:
            msg += "\n\n失败项：\n" + "\n".join(failed[:8])
            if len(failed) > 8:
                msg += f"\n... 等 {len(failed)} 个"

        def _show_done_and_open():
            messagebox.showinfo("处理完成", msg)
            try:
                should_open = bool(self.settings.get("auto_open_output", getattr(self, "auto_open_output", True)))
                output_dir = getattr(progress_window, "output_dir", "")
                if should_open and output_dir:
                    out_path = Path(output_dir)
                    if out_path.exists():
                        open_in_explorer(out_path)
                    else:
                        self.status_text.configure(text=f"{task_name}已完成（输出目录不存在）")
            except Exception as e:
                self.status_text.configure(text=f"{task_name}已完成，但打开输出目录失败：{e}")

        self.root.after(450, _show_done_and_open)


    def show_settings(self):
        SettingsDialog(self.root, self.style, self._save_settings, self._load_settings, self.settings)

    def show_about(self):
        AboutDialog(self.root)


def main():
    root = tb.Window(themename="flatly")
    root.withdraw()
    splash = SplashScreen(root)
    root.after(1000, splash.destroy)
    root.after(1020, root.deiconify)
    ImageToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
