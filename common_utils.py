
import io
import json
import os
import re
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageOps, ImageTk, ImageChops, ImageStat, ImageFilter
import ttkbootstrap as tb
from ttkbootstrap.constants import *

SUPPORTED_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'}

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE = DATA_DIR / "error.log"
PRESET_DIR = DATA_DIR / "presets"
PRESET_DIR.mkdir(parents=True, exist_ok=True)
APP_SETTINGS_FILE = DATA_DIR / "ui_settings.json"




def log_error(message: str):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(message.rstrip() + "\n")
    except Exception:
        pass


def open_in_explorer(path: Path):
    try:
        if os.name == "nt":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(path)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        log_error(f'open_in_explorer failed: {e}')


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTS


def natural_sort_key(path_obj):
    text = path_obj.name if hasattr(path_obj, 'name') else str(path_obj)
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', text)]


def list_images(input_path: Path, include_subdirs=True, exclude_path: Path = None):
    if input_path.is_file() and is_image_file(input_path):
        return [(input_path, Path(input_path.name))]
    images = []
    if not input_path.exists():
        return images
    if include_subdirs:
        for root, _, files in os.walk(input_path):
            root_path = Path(root)
            if exclude_path:
                try:
                    root_path.relative_to(exclude_path)
                    continue
                except ValueError:
                    pass
            for file in files:
                full_path = root_path / file
                if is_image_file(full_path):
                    images.append((full_path, full_path.relative_to(input_path)))
    else:
        for file in input_path.iterdir():
            if is_image_file(file):
                images.append((file, Path(file.name)))
    images.sort(key=lambda x: natural_sort_key(x[1]))
    return images


def default_output_dir(input_value: str) -> str:
    if not input_value:
        return ''
    p = Path(input_value)
    return str((p.parent if p.is_file() else p) / '结果')


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_image_by_format(img: Image.Image, output_path: Path, format_type: str, jpg_quality=95, png_compress_level=6, webp_quality=90):
    format_type = (format_type or 'original').lower()
    if format_type == 'original':
        suffix = output_path.suffix.lower()
    elif format_type == 'jpg':
        suffix = '.jpg'
        output_path = output_path.with_suffix('.jpg')
    elif format_type == 'png':
        suffix = '.png'
        output_path = output_path.with_suffix('.png')
    elif format_type == 'webp':
        suffix = '.webp'
        output_path = output_path.with_suffix('.webp')
    else:
        suffix = output_path.suffix.lower()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if suffix in {'.jpg', '.jpeg'}:
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.getchannel('A'))
            img = bg
        elif img.mode not in {'RGB', 'L'}:
            img = img.convert('RGB')
        img.save(output_path, 'JPEG', quality=jpg_quality, optimize=True)
    elif suffix == '.png':
        img.save(output_path, 'PNG', optimize=True, compress_level=png_compress_level)
    elif suffix == '.webp':
        if img.mode not in {'RGB', 'RGBA', 'L'}:
            img = img.convert('RGBA')
        img.save(output_path, 'WEBP', quality=webp_quality, method=6)
    else:
        img.save(output_path)
    return output_path


def open_image_with_exif(path: Path):
    img = Image.open(path)
    return ImageOps.exif_transpose(img)


def create_input_row(parent, label_text, textvariable, callback=None):
    row = tb.Frame(parent)
    row.pack(fill=X, pady=5)
    tb.Label(row, text=label_text, width=10, anchor=W).pack(side=LEFT)
    entry = tb.Entry(row, textvariable=textvariable)
    entry.pack(side=LEFT, fill=X, expand=YES, padx=6)

    menu_btn = tb.Menubutton(row, text='选择输入', bootstyle='primary-outline', width=12)
    menu = tk.Menu(menu_btn, tearoff=0)
    menu_btn.configure(menu=menu)
    menu.add_command(label='选择图片文件', command=lambda: _pick_file(textvariable, callback))
    menu.add_command(label='选择文件夹', command=lambda: _pick_dir(textvariable, callback))
    menu_btn.pack(side=LEFT)
    return entry


def create_output_row(parent, label_text, textvariable):
    row = tb.Frame(parent)
    row.pack(fill=X, pady=5)
    tb.Label(row, text=label_text, width=10, anchor=W).pack(side=LEFT)
    entry = tb.Entry(row, textvariable=textvariable)
    entry.pack(side=LEFT, fill=X, expand=YES, padx=6)
    tb.Button(row, text='浏览', command=lambda: _pick_dir(textvariable), bootstyle='secondary-outline', width=12).pack(side=LEFT)
    return entry


def _pick_file(var, callback=None):
    filename = filedialog.askopenfilename(
        title='选择图片文件',
        filetypes=[('图片文件', '*.png *.jpg *.jpeg *.bmp *.gif *.webp'), ('所有文件', '*.*')]
    )
    if filename:
        var.set(filename)
        if callback:
            callback(filename)


def _pick_dir(var, callback=None):
    directory = filedialog.askdirectory(title='选择文件夹')
    if directory:
        var.set(directory)
        if callback:
            callback(directory)






class ImagePreview:
    def __init__(self, parent, title='图片预览'):
        frame = tb.LabelFrame(parent, text=title)
        inner = tb.Frame(frame, padding=10)
        frame.pack(fill=BOTH, expand=YES)
        inner.pack(fill=BOTH, expand=YES)

        self.view_mode = tk.StringVar(value="single")
        self.zoom_mode = tk.StringVar(value="fit")
        self.zoom_percent = 100
        self.manual_zoom = 1.0

        self._photo_left = None
        self._photo_right = None
        self._source_left = None
        self._source_right = None
        self._thumb_items = []
        self._pan_state = {
            "left": {"x": 0, "y": 0, "start_x": 0, "start_y": 0, "dragging": False},
            "right": {"x": 0, "y": 0, "start_x": 0, "start_y": 0, "dragging": False},
        }

        topbar = tb.Frame(inner)
        topbar.pack(fill=X, pady=(0, 8))
        tb.Label(topbar, text="预览模式:", bootstyle="secondary").pack(side=LEFT)
        tb.Radiobutton(topbar, text="单预览", variable=self.view_mode, value="single", bootstyle="toolbutton-outline", command=self._switch_to_fit_and_redraw).pack(side=LEFT, padx=4)
        tb.Radiobutton(topbar, text="前后对比", variable=self.view_mode, value="dual", bootstyle="toolbutton-outline", command=self._switch_to_fit_and_redraw).pack(side=LEFT, padx=4)

        self.preview_tools = tb.Frame(inner)
        self.preview_tools.pack(fill=X, pady=(0, 8))
        tb.Button(self.preview_tools, text="一键适配", bootstyle="secondary-outline", command=self.set_fit).pack(side=LEFT)
        tb.Button(self.preview_tools, text="100% 预览", bootstyle="secondary-outline", command=self.set_actual).pack(side=LEFT, padx=6)
        self.zoom_label = tb.Label(self.preview_tools, text="缩放比例: 100%", bootstyle="secondary")
        self.zoom_label.pack(side=LEFT, padx=(12, 0))

        body = tb.Frame(inner)
        body.pack(fill=BOTH, expand=YES)

        self.thumb_list = tk.Listbox(body, width=18, exportselection=False)
        self.thumb_list.pack(side=LEFT, fill=Y, padx=(0, 6))
        self.thumb_list.bind("<<ListboxSelect>>", self._on_thumb_select)

        canvas_wrap = tb.Frame(body)
        canvas_wrap.pack(side=LEFT, fill=BOTH, expand=YES)
        canvas_wrap.columnconfigure(0, weight=1)
        canvas_wrap.columnconfigure(1, weight=1)
        canvas_wrap.rowconfigure(0, weight=0)
        canvas_wrap.rowconfigure(1, weight=1)

        self.left_title = tb.Label(canvas_wrap, text='原图', bootstyle='secondary')
        self.left_title.grid(row=0, column=0, sticky='w', padx=(4, 4), pady=(0, 4))
        self.right_title = tb.Label(canvas_wrap, text='结果图', bootstyle='secondary')
        self.right_title.grid(row=0, column=1, sticky='e', padx=(4, 4), pady=(0, 4))

        self.canvas_left = tk.Canvas(canvas_wrap, bg='#1f2430', highlightthickness=1, highlightbackground='#3b4252', cursor='fleur')
        self.canvas_right = tk.Canvas(canvas_wrap, bg='#1f2430', highlightthickness=1, highlightbackground='#3b4252', cursor='fleur')
        self.canvas_left.grid(row=1, column=0, sticky='nsew', padx=(0, 4))
        self.canvas_right.grid(row=1, column=1, sticky='nsew', padx=(4, 0))

        self.tip = tb.Label(inner, text='拖拽图片或选择文件后可在此预览', bootstyle='secondary')
        self.tip.pack(fill=X, pady=(8, 0))

        self.info = tb.Label(inner, text='暂无预览', justify=LEFT, bootstyle='secondary')
        self.info.pack(fill=X, pady=(6, 0))

        self._bind_canvas(self.canvas_left, "left")
        self._bind_canvas(self.canvas_right, "right")
        self._apply_mode()

    def _bind_canvas(self, canvas, side):
        canvas.bind('<Configure>', self._redraw)
        canvas.bind('<Double-Button-1>', self._on_double_click_fit)
        canvas.bind('<ButtonPress-1>', lambda e, s=side: self._start_pan(s, e))
        canvas.bind('<B1-Motion>', lambda e, s=side: self._do_pan(s, e))
        canvas.bind('<ButtonRelease-1>', lambda e, s=side: self._end_pan(s, e))
        canvas.bind('<MouseWheel>', self._on_mousewheel)
        canvas.bind('<Button-4>', self._on_mousewheel)
        canvas.bind('<Button-5>', self._on_mousewheel)

    def _switch_to_fit_and_redraw(self):
        self.zoom_mode.set("fit")
        self.manual_zoom = 1.0
        self._reset_pan()
        self._redraw()

    def _start_pan(self, side, event):
        state = self._pan_state[side]
        state["dragging"] = True
        state["start_x"] = event.x
        state["start_y"] = event.y

    def _do_pan(self, side, event):
        state = self._pan_state[side]
        if not state["dragging"]:
            return
        dx = event.x - state["start_x"]
        dy = event.y - state["start_y"]
        state["x"] += dx
        state["y"] += dy
        state["start_x"] = event.x
        state["start_y"] = event.y
        self.tip.configure(text='预览模式：拖动画布')
        self._redraw()

    def _end_pan(self, side, event=None):
        self._pan_state[side]["dragging"] = False

    def _reset_pan(self):
        for side in ("left", "right"):
            self._pan_state[side]["x"] = 0
            self._pan_state[side]["y"] = 0
            self._pan_state[side]["dragging"] = False

    def _on_double_click_fit(self, event=None):
        self.set_fit()

    def _on_mousewheel(self, event):
        direction = 0
        if hasattr(event, "delta") and event.delta:
            direction = 1 if event.delta > 0 else -1
        elif getattr(event, "num", None) == 4:
            direction = 1
        elif getattr(event, "num", None) == 5:
            direction = -1
        if direction == 0:
            return
        self.zoom_mode.set("manual")
        step = 1.1 if direction > 0 else 0.9
        self.manual_zoom = max(0.05, min(8.0, self.manual_zoom * step))
        self.tip.configure(text='预览模式：鼠标滚轮缩放')
        self._redraw()

    def set_fit(self):
        self.zoom_mode.set("fit")
        self.manual_zoom = 1.0
        self._reset_pan()
        self.tip.configure(text='预览模式：一键适配')
        self._redraw()

    def set_actual(self):
        self.zoom_mode.set("actual")
        self.manual_zoom = 1.0
        self._reset_pan()
        self.tip.configure(text='预览模式：100% 预览')
        self._redraw()

    def set_thumbnails(self, paths):
        self._thumb_items = [str(p) for p in paths[:200]]
        self.thumb_list.delete(0, 'end')
        for p in self._thumb_items:
            self.thumb_list.insert('end', Path(p).name)
        if self._thumb_items:
            self.thumb_list.selection_clear(0, 'end')
            self.thumb_list.selection_set(0)
        else:
            self.thumb_list.selection_clear(0, 'end')

    def _on_thumb_select(self, _event=None):
        sel = self.thumb_list.curselection()
        if not sel or not self._thumb_items:
            return
        idx = sel[0]
        if 0 <= idx < len(self._thumb_items):
            self.show(self._thumb_items[idx])

    def show(self, path, prefix_text=''):
        if not path:
            self.clear()
            return
        p = Path(path)
        try:
            img = open_image_with_exif(p)
            self._source_left = img.copy()
            self._source_right = None
            self.view_mode.set("single")
            self.set_fit()
            size_kb = p.stat().st_size / 1024 if p.exists() else 0
            prefix = f'{prefix_text}\n' if prefix_text else ''
            self.left_title.configure(text='原图')
            self.right_title.configure(text='结果图')
            self.info.configure(text=f'{prefix}文件：{p.name}\n分辨率：{img.width} x {img.height}\n大小：{size_kb:.1f} KB')
        except Exception as e:
            self.clear(f'预览失败：{e}')

    def show_dual(self, before_path=None, after_path=None, prefix_text=''):
        self._source_left = None
        self._source_right = None
        left_info = ''
        right_info = ''
        try:
            if before_path:
                bp = Path(before_path)
                self._source_left = open_image_with_exif(bp).copy()
                left_info = f'原图：{bp.name}'
            if after_path:
                ap = Path(after_path)
                self._source_right = open_image_with_exif(ap).copy()
                right_info = f'结果图：{ap.name}'
            self.view_mode.set("dual")
            self.set_fit()
            extra = '\n'.join([t for t in [left_info, right_info] if t])
            prefix = f'{prefix_text}\n' if prefix_text else ''
            self.left_title.configure(text='原图')
            self.right_title.configure(text='结果图')
            self.info.configure(text=f'{prefix}{extra or "当前无对比结果"}')
        except Exception as e:
            self.clear(f'预览失败：{e}')

    def show_dual_images(self, before_img=None, after_img=None, before_label='原图', after_label='结果图', prefix_text=''):
        self._source_left = before_img.copy() if before_img is not None else None
        self._source_right = after_img.copy() if after_img is not None else None
        self.view_mode.set("dual")
        self.set_fit()
        parts = []
        if self._source_left is not None:
            parts.append(f'{before_label}：内存预览')
        if self._source_right is not None:
            parts.append(f'{after_label}：实时预览')
        prefix = f'{prefix_text}\n' if prefix_text else ''
        self.left_title.configure(text=before_label)
        self.right_title.configure(text=after_label)
        self.info.configure(text=f'{prefix}' + '\n'.join(parts))

    def show_folder_preview(self, folder_path, image_count=0, include_subdirs=True):
        folder = Path(folder_path)
        images = list_images(folder, include_subdirs)
        self.set_thumbnails([p for p, _ in images])
        if not images:
            self.clear('文件夹内没有可预览的图片')
            return
        note = f'文件夹：{folder.name}\n图片数量：{image_count or len(images)}'
        self.show(str(images[0][0]), prefix_text=note)

    def _render_to_canvas(self, canvas, img, side):
        canvas.delete('all')
        w = max(120, int(canvas.winfo_width() or 420))
        h = max(120, int(canvas.winfo_height() or 420))
        if img is None:
            canvas.create_text(w // 2, h // 2, text='暂无图像', fill='#888888')
            return None

        if self.zoom_mode.get() == "fit":
            avail_w = max(40, w - 24)
            avail_h = max(40, h - 24)
            ratio = min(avail_w / max(1, img.width), avail_h / max(1, img.height))
        elif self.zoom_mode.get() == "actual":
            ratio = 1.0
        else:
            ratio = self.manual_zoom

        ratio = max(0.05, min(8.0, ratio))
        render_w = max(1, int(img.width * ratio))
        render_h = max(1, int(img.height * ratio))
        copy = img.resize((render_w, render_h), Image.Resampling.LANCZOS)
        self.zoom_percent = max(1, int(ratio * 100))
        self.zoom_label.configure(text=f"缩放比例: {self.zoom_percent}%")

        photo = ImageTk.PhotoImage(copy)
        pan = self._pan_state[side]
        x = (w // 2) + pan["x"]
        y = (h // 2) + pan["y"]
        shadow_offset = 6
        canvas.create_rectangle(
            x - render_w // 2 + shadow_offset,
            y - render_h // 2 + shadow_offset,
            x + render_w // 2 + shadow_offset,
            y + render_h // 2 + shadow_offset,
            outline='',
            fill='#11151c'
        )
        canvas.create_image(x, y, image=photo, anchor='center')
        return photo

    def _apply_mode(self):
        if self.view_mode.get() == 'single':
            self.canvas_left.grid(row=1, column=0, columnspan=2, sticky='nsew', padx=(0, 0))
            self.left_title.grid(row=0, column=0, columnspan=2, sticky='w', padx=(4, 4), pady=(0, 4))
            self.canvas_right.grid_remove()
            self.right_title.grid_remove()
        else:
            self.left_title.grid(row=0, column=0, sticky='w', padx=(4, 4), pady=(0, 4))
            self.right_title.grid(row=0, column=1, sticky='e', padx=(4, 4), pady=(0, 4))
            self.canvas_left.grid(row=1, column=0, columnspan=1, sticky='nsew', padx=(0, 4))
            self.canvas_right.grid(row=1, column=1, columnspan=1, sticky='nsew', padx=(4, 0))

    def _redraw(self, _event=None):
        self._apply_mode()
        self._photo_left = self._render_to_canvas(self.canvas_left, self._source_left, "left")
        if self.view_mode.get() == 'dual':
            self._photo_right = self._render_to_canvas(self.canvas_right, self._source_right, "right")
        else:
            self._photo_right = None

    def clear(self, text='暂无预览'):
        self._photo_left = None
        self._photo_right = None
        self._source_left = None
        self._source_right = None
        self.thumb_list.delete(0, 'end')
        self.canvas_left.delete('all')
        self.canvas_right.delete('all')
        self.zoom_mode.set("fit")
        self.manual_zoom = 1.0
        self._reset_pan()
        self.zoom_label.configure(text='缩放比例: 100%')
        self.tip.configure(text='拖拽图片或选择文件后可在此预览')
        self.info.configure(text=text)


class PreviewUpdater:
    def __init__(self, root, preview, get_source_image, render_result, delay_ms=250):
        self.root = root
        self.preview = preview
        self.get_source_image = get_source_image
        self.render_result = render_result
        self.delay_ms = delay_ms
        self._after_id = None

    def trigger(self, *_):
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = self.root.after(self.delay_ms, self.refresh)

    def refresh(self):
        self._after_id = None
        try:
            src = self.get_source_image()
            if src is None:
                return
            result = self.render_result(src.copy())
            if result is not None:
                self.preview.show_dual_images(src, result, prefix_text='实时参数预览')
        except Exception as e:
            log_error(f'PreviewUpdater.refresh failed: {e}')


def bind_drop_to_widget(widget, setter, accept='any'):
    try:
        import windnd
    except Exception:
        return False

    def _normalize(raw):
        if isinstance(raw, bytes):
            for enc in ('gbk', 'utf-8', 'mbcs'):
                try:
                    return raw.decode(enc)
                except Exception:
                    pass
            return raw.decode(errors='ignore')
        return str(raw)

    def _on_drop(files):
        if not files:
            return
        # single path; if multiple passed, setter can handle list when accept='multi'
        norm = []
        for raw in files:
            path = _normalize(raw).strip().strip('"')
            if path:
                norm.append(path)
        if not norm:
            return
        if accept == 'multi':
            setter(norm)
            return
        for path in norm:
            p = Path(path)
            if not p.exists():
                continue
            if accept == 'file' and not p.is_file():
                continue
            if accept == 'dir' and not p.is_dir():
                continue
            if accept == 'image' and not (p.is_file() and is_image_file(p)):
                continue
            setter(path)
            break

    try:
        windnd.hook_dropfiles(widget, func=_on_drop)
        return True
    except Exception:
        return False


def image_hash(img: Image.Image, hash_size=8):
    g = img.convert('L').resize((hash_size + 1, hash_size))
    pixels = list(g.getdata())
    rows = []
    for y in range(hash_size):
        row = []
        for x in range(hash_size):
            left = pixels[y * (hash_size + 1) + x]
            right = pixels[y * (hash_size + 1) + x + 1]
            row.append('1' if left > right else '0')
        rows.append(''.join(row))
    bits = ''.join(rows)
    return int(bits, 2)


def hamming_distance(a, b):
    return bin(a ^ b).count('1')


def read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def remove_exif(img: Image.Image):
    data = list(img.getdata())
    clean = Image.new(img.mode, img.size)
    clean.putdata(data)
    return clean


def add_border(img: Image.Image, border_px=20, color="#FFFFFF"):
    return ImageOps.expand(img, border=border_px, fill=color)


def add_background(img: Image.Image, color="#FFFFFF"):
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    bg = Image.new('RGBA', img.size, color)
    bg.alpha_composite(img)
    return bg


def image_difference_score(img1: Image.Image, img2: Image.Image):
    a = img1.convert('RGB').resize((256, 256))
    b = img2.convert('RGB').resize((256, 256))
    diff = ImageChops.difference(a, b)
    stat = ImageStat.Stat(diff)
    return sum(stat.mean) / len(stat.mean)


def append_recent_record(path: Path, record, limit=20):
    data = read_json(path, [])
    data.insert(0, record)
    data = data[:limit]
    write_json(path, data)
    return data


def preset_file(module_name: str) -> Path:
    return PRESET_DIR / f"{module_name}.json"


def save_module_preset(module_name: str, preset: dict):
    path = preset_file(module_name)
    presets = read_json(path, [])
    presets.append(preset)
    write_json(path, presets)
    return presets


def load_module_presets(module_name: str):
    return read_json(preset_file(module_name), [])


def latest_module_preset(module_name: str):
    presets = load_module_presets(module_name)
    return presets[-1] if presets else None


def save_app_settings(settings: dict):
    write_json(APP_SETTINGS_FILE, settings)


def load_app_settings():
    return read_json(APP_SETTINGS_FILE, {"theme": "flatly", "remember_theme": True, "auto_open_output": True})


class PresetPickerDialog(tk.Toplevel):
    def __init__(self, master, module_name: str):
        super().__init__(master)
        self.title("选择模板")
        self.geometry("520x360")
        self.transient(master)
        self.grab_set()
        self.result = None
        self.module_name = module_name

        wrap = tb.Frame(self, padding=16)
        wrap.pack(fill=BOTH, expand=YES)

        tb.Label(wrap, text=f"模块模板：{module_name}", font=("微软雅黑", 12, "bold")).pack(anchor=W, pady=(0, 10))

        self.presets = load_module_presets(module_name)
        self.listbox = tk.Listbox(wrap, height=12)
        self.listbox.pack(fill=BOTH, expand=YES)
        self.listbox.bind("<Double-Button-1>", lambda e: self.on_choose())
        for idx, p in enumerate(self.presets, 1):
            name = p.get("preset_name") or f"模板{idx}"
            self.listbox.insert("end", name)

        foot = tb.Frame(wrap)
        foot.pack(fill=X, pady=(10, 0))
        tb.Button(foot, text="选择", bootstyle="primary", command=self.on_choose, width=12).pack(side=RIGHT)
        tb.Button(foot, text="删除选中", bootstyle="danger-outline", command=self.on_delete, width=12).pack(side=RIGHT, padx=8)
        tb.Button(foot, text="关闭", bootstyle="secondary-outline", command=self.destroy, width=12).pack(side=RIGHT)

    def on_choose(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.result = self.presets[sel[0]]
        self.destroy()

    def on_delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        del self.presets[idx]
        write_json(preset_file(self.module_name), self.presets)
        self.listbox.delete(idx)



def make_card(parent, title: str, subtext: str = ""):
    box = tb.LabelFrame(parent, text=title)
    box.pack(fill=X, pady=(0, 10))
    inner = tb.Frame(box, padding=12)
    inner.pack(fill=X)
    if subtext:
        tb.Label(inner, text=subtext, bootstyle="secondary").pack(anchor=W, pady=(0, 8))
    return box, inner


def make_primary_button(parent, text, command):
    btn = tb.Button(parent, text=text, command=command, bootstyle="primary", width=18)
    return btn


def make_secondary_button(parent, text, command):
    btn = tb.Button(parent, text=text, command=command, bootstyle="secondary-outline", width=18)
    return btn
