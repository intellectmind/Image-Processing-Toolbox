
import os
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

import ttkbootstrap as tb
from ttkbootstrap.constants import *
from PIL import Image, ImageTk, ImageDraw, ImageFilter, ImageChops

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

from common_utils import create_input_row, create_output_row, default_output_dir, make_card, make_primary_button, make_secondary_button, open_image_with_exif, save_image_by_format, bind_drop_to_widget



class SaveCompareDialog(tb.Toplevel):
    def __init__(self, master, before_img, after_img, on_save):
        super().__init__(master)
        self.title("保存前确认")
        self.geometry("920x620")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)
        self.on_save = on_save
        self.before_img = before_img
        self.after_img = after_img
        self.tk_before = None
        self.tk_after = None

        wrap = tb.Frame(self, padding=16)
        wrap.pack(fill=BOTH, expand=YES)

        tb.Label(wrap, text="保存前对比", font=("微软雅黑", 16, "bold")).pack(anchor=W, pady=(0, 10))
        tb.Label(wrap, text="确认修复效果后再保存，更像专业修图软件的工作流。", bootstyle="secondary").pack(anchor=W, pady=(0, 10))

        compare = tb.Frame(wrap)
        compare.pack(fill=BOTH, expand=YES)

        left = tb.LabelFrame(compare, text="修复前")
        left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 8))
        right = tb.LabelFrame(compare, text="修复后")
        right.pack(side=LEFT, fill=BOTH, expand=YES, padx=(8, 0))
        self.before_canvas = tk.Canvas(left, bg='#1f2430', highlightthickness=1, highlightbackground='#3b4252')
        self.before_canvas.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        self.after_canvas = tk.Canvas(right, bg='#1f2430', highlightthickness=1, highlightbackground='#3b4252')
        self.after_canvas.pack(fill=BOTH, expand=YES, padx=10, pady=10)

        foot = tb.Frame(wrap)
        foot.pack(fill=X, pady=(12, 0))
        tb.Button(foot, text="重新修复", bootstyle="secondary-outline", command=self.destroy, width=14).pack(side=RIGHT)
        tb.Button(foot, text="直接保存", bootstyle="primary", command=self._save_and_close, width=14).pack(side=RIGHT, padx=8)

        self.after(50, self.render_preview)

    def _fit_img(self, img, max_w, max_h):
        copy = img.copy()
        copy.thumbnail((max_w, max_h))
        return copy

    def render_preview(self):
        for canvas, img, attr in [
            (self.before_canvas, self.before_img, "tk_before"),
            (self.after_canvas, self.after_img, "tk_after"),
        ]:
            canvas.delete("all")
            w = max(200, int(canvas.winfo_width() or 400))
            h = max(200, int(canvas.winfo_height() or 400))
            preview = self._fit_img(img, w - 20, h - 20)
            photo = ImageTk.PhotoImage(preview)
            setattr(self, attr, photo)
            canvas.create_image(w // 2, h // 2, image=photo, anchor="center")

    def _save_and_close(self):
        self.on_save()
        self.destroy()


class RetouchModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing

        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.brush_size = tk.IntVar(value=18)
        self.brush_hardness = tk.IntVar(value=70)
        self.strength = tk.IntVar(value=5)
        self.output_format = tk.StringVar(value="png")
        self.tool_mode = tk.StringVar(value="paint")
        self.compare_mode = tk.BooleanVar(value=False)
        self.show_mask_overlay = tk.BooleanVar(value=True)
        self.show_loupe = tk.BooleanVar(value=True)
        self.show_feather_preview = tk.BooleanVar(value=True)

        self.original_image = None
        self.preview_image = None
        self.repaired_image = None
        self.mask_image = None
        self.tk_preview = None
        self.tk_loupe = None
        self.scale_ratio = 1.0
        self.last_x = None
        self.last_y = None
        self.last_cx = None   # canvas坐标，用于即时笔刷绘制
        self.last_cy = None
        self._cached_disp = None        # 缓存缩放后的底图
        self._cached_disp_size = None
        self._cached_disp_base = None
        self.undo_stack = []
        self.redo_stack = []
        self.cursor_img_xy = None
        self.history_records = []

        self.input_path.trace_add('write', self.on_input_changed)
        self.create_ui()
        self.bind_shortcuts()
        self.on_input_changed()

    def create_ui(self):
        body = tb.Frame(self.parent_frame)
        body.pack(fill=BOTH, expand=YES)

        left = tb.Frame(body)
        left.pack(side=LEFT, fill=Y, padx=(0, 12))
        right = tb.Frame(body)
        right.pack(side=LEFT, fill=BOTH, expand=YES)

        io_box, io_inner = make_card(left, '输入输出', '选择图片和结果保存位置')
        self.input_entry = create_input_row(io_inner, '输入路径:', self.input_path)
        create_output_row(io_inner, '输出目录:', self.output_dir)

        cfg, cfg_inner = make_card(left, '修复设置', '调整画笔、硬度、强度与显示方式')

        row0 = tb.Frame(cfg_inner)
        row0.pack(fill=X, pady=4)
        tb.Label(row0, text='工具模式:', width=10, anchor=W).pack(side=LEFT)
        tb.Radiobutton(row0, text='涂抹', variable=self.tool_mode, value='paint', bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)
        tb.Radiobutton(row0, text='橡皮擦', variable=self.tool_mode, value='erase', bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        row1 = tb.Frame(cfg_inner)
        row1.pack(fill=X, pady=4)
        tb.Label(row1, text='笔刷大小:', width=10, anchor=W).pack(side=LEFT)
        tb.Scale(row1, from_=4, to=80, variable=self.brush_size, orient=HORIZONTAL, command=lambda _=None: self.render_preview()).pack(side=LEFT, fill=X, expand=YES)
        self.brush_label = tb.Label(row1, text='18 px', width=8)
        self.brush_label.pack(side=LEFT, padx=(6,0))
        self.brush_size.trace_add('write', lambda *_: self.brush_label.configure(text=f'{self.brush_size.get()} px'))

        row_h = tb.Frame(cfg_inner)
        row_h.pack(fill=X, pady=4)
        tb.Label(row_h, text='画笔硬度:', width=10, anchor=W).pack(side=LEFT)
        tb.Scale(row_h, from_=0, to=100, variable=self.brush_hardness, orient=HORIZONTAL, command=lambda _=None: self.render_preview()).pack(side=LEFT, fill=X, expand=YES)
        self.hardness_label = tb.Label(row_h, text='70%', width=8)
        self.hardness_label.pack(side=LEFT, padx=(6,0))
        self.brush_hardness.trace_add('write', lambda *_: self.hardness_label.configure(text=f'{self.brush_hardness.get()}%'))

        row2 = tb.Frame(cfg_inner)
        row2.pack(fill=X, pady=4)
        tb.Label(row2, text='修复强度:', width=10, anchor=W).pack(side=LEFT)
        tb.Scale(row2, from_=1, to=15, variable=self.strength, orient=HORIZONTAL).pack(side=LEFT, fill=X, expand=YES)
        self.strength_label = tb.Label(row2, text='5', width=8)
        self.strength_label.pack(side=LEFT, padx=(6,0))
        self.strength.trace_add('write', lambda *_: self.strength_label.configure(text=str(self.strength.get())))

        row3 = tb.Frame(cfg_inner)
        row3.pack(fill=X, pady=4)
        tb.Label(row3, text='输出格式:', width=10, anchor=W).pack(side=LEFT)
        for lab, val in [('PNG','png'),('JPG','jpg'),('WEBP','webp')]:
            tb.Radiobutton(row3, text=lab, variable=self.output_format, value=val, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        row4 = tb.Frame(cfg_inner)
        row4.pack(fill=X, pady=4)
        tb.Checkbutton(row4, text='修复前后分屏对比', variable=self.compare_mode, bootstyle='round-toggle', command=self.render_preview).pack(anchor=W)

        row5 = tb.Frame(cfg_inner)
        row5.pack(fill=X, pady=4)
        tb.Checkbutton(row5, text='显示蒙版覆盖层', variable=self.show_mask_overlay, bootstyle='round-toggle', command=self.render_preview).pack(anchor=W)
        tb.Checkbutton(row5, text='显示局部放大镜', variable=self.show_loupe, bootstyle='round-toggle', command=self.render_preview).pack(anchor=W, pady=(6,0))
        tb.Checkbutton(row5, text='显示羽化预览', variable=self.show_feather_preview, bootstyle='round-toggle', command=self.render_preview).pack(anchor=W, pady=(6,0))

        btns_box, btns = make_card(left, '快捷操作', '常用动作统一放在这里')
        make_secondary_button(btns, '撤销  Ctrl+Z', self.undo).pack(fill=X, pady=3)
        make_secondary_button(btns, '重做  Ctrl+Y', self.redo).pack(fill=X, pady=3)
        make_secondary_button(btns, '清空涂抹  Ctrl+L', self.clear_mask).pack(fill=X, pady=3)
        tb.Button(btns, text='预览修复结果  Space', bootstyle='info-outline', command=self.preview_repair, width=18).pack(fill=X, pady=3)
        make_primary_button(btns, '保存修复结果  Ctrl+S', self.save_repair).pack(fill=X, pady=3)

        note, note_inner = make_card(left, '说明 / 快捷键', '帮助你更快上手普通修复')
        tb.Label(
            note_inner,
            text='普通修复适合去小污点、划痕、杂物。\n快捷键：Ctrl+Z 撤销，Ctrl+Y 重做，Ctrl+S 保存，Ctrl+L 清空，Space 预览。',
            justify=LEFT,
            wraplength=240,
            bootstyle='secondary'
        ).pack(anchor=W)

        history_box, history_inner = make_card(left, '修复历史面板', '最近的修复动作会显示在这里')
        history_box.pack(fill=BOTH, expand=YES)
        history_inner.pack(fill=BOTH, expand=YES)
        self.history_list = tk.Listbox(history_inner, height=10)
        self.history_list.pack(fill=BOTH, expand=YES)

        preview_box = tb.LabelFrame(right, text='普通修复工作台')
        preview_box.pack(fill=BOTH, expand=YES)
        preview_inner = tb.Frame(preview_box, padding=10)
        preview_inner.pack(fill=BOTH, expand=YES)

        self.canvas = tk.Canvas(preview_inner, bg='#1f2430', highlightthickness=1, highlightbackground='#3b4252', cursor='crosshair')
        self.canvas.pack(fill=BOTH, expand=YES)
        self.canvas.bind('<Configure>', self.render_preview)
        self.canvas.bind('<ButtonPress-1>', self.start_paint)
        self.canvas.bind('<B1-Motion>', self.paint_move)
        self.canvas.bind('<ButtonRelease-1>', self.end_paint)
        self.canvas.bind('<Motion>', self.track_cursor)
        # 拖拽支持：拖图片到输入框或画布均可加载
        bind_drop_to_widget(self.input_entry, lambda p: self.input_path.set(p), accept='image')
        bind_drop_to_widget(self.canvas,      lambda p: self.input_path.set(p), accept='image')

        self.info_label = tb.Label(preview_inner, text='加载图片后，在图上直接涂抹需要修复的区域。', bootstyle='secondary')
        self.info_label.pack(fill=X, pady=(8,0))

    def bind_shortcuts(self):
        self.parent_frame.bind_all('<Control-z>', lambda e: self.undo())
        self.parent_frame.bind_all('<Control-y>', lambda e: self.redo())
        self.parent_frame.bind_all('<Control-s>', lambda e: self.save_repair())
        self.parent_frame.bind_all('<Control-l>', lambda e: self.clear_mask())
        self.parent_frame.bind_all('<space>', lambda e: self.preview_repair())

    def add_history(self, text):
        self.history_records.insert(0, text)
        self.history_records = self.history_records[:30]
        self.history_list.delete(0, 'end')
        for item in self.history_records:
            self.history_list.insert('end', item)

    def push_undo(self):
        if self.mask_image is not None:
            self.undo_stack.append(self.mask_image.copy())
            self.undo_stack = self.undo_stack[-30:]
            self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack or self.mask_image is None:
            return
        self.redo_stack.append(self.mask_image.copy())
        self.mask_image = self.undo_stack.pop()
        self.repaired_image = None
        self.preview_image = self.original_image.copy() if self.original_image else None
        self.add_history('撤销一次操作')
        self.render_preview()

    def redo(self):
        if not self.redo_stack or self.mask_image is None:
            return
        self.undo_stack.append(self.mask_image.copy())
        self.mask_image = self.redo_stack.pop()
        self.repaired_image = None
        self.preview_image = self.original_image.copy() if self.original_image else None
        self.add_history('重做一次操作')
        self.render_preview()

    def on_input_changed(self, *_):
        self.output_dir.set(default_output_dir(self.input_path.get()))
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            try:
                self.original_image = open_image_with_exif(p).convert('RGB')
                self.mask_image = Image.new('L', self.original_image.size, 0)
                self.preview_image = self.original_image.copy()
                self.repaired_image = None
                self._cached_disp = None   # 清除底图缓存
                self.undo_stack.clear()
                self.redo_stack.clear()
                self.history_records.clear()
                self.add_history(f'载入图片：{p.name}')
                self.render_preview()
                self.info_label.configure(text=f'已加载：{p.name}  |  分辨率：{self.original_image.width} x {self.original_image.height}')
            except Exception as e:
                self.info_label.configure(text=f'加载失败：{e}')
        else:
            self.original_image = None
            self.mask_image = None
            self.preview_image = None
            self.repaired_image = None
            self._cached_disp = None
            self.render_preview()

    def track_cursor(self, event):
        if self.original_image is None:
            return
        self.cursor_img_xy = self.canvas_to_image_xy(event.x, event.y)
        if self.show_loupe.get():
            self.render_preview()

    def render_loupe(self, cw, ch):
        if not self.show_loupe.get() or self.original_image is None or self.cursor_img_xy is None:
            return
        x, y = self.cursor_img_xy
        src = self.repaired_image if self.repaired_image is not None else self.original_image
        crop_size = 80
        x1 = max(0, x - crop_size // 2)
        y1 = max(0, y - crop_size // 2)
        x2 = min(src.width, x1 + crop_size)
        y2 = min(src.height, y1 + crop_size)
        crop = src.crop((x1, y1, x2, y2)).resize((140, 140), Image.Resampling.NEAREST)
        draw = ImageDraw.Draw(crop)
        draw.line((70, 0, 70, 140), fill='red', width=1)
        draw.line((0, 70, 140, 70), fill='red', width=1)
        self.tk_loupe = ImageTk.PhotoImage(crop)
        lx, ly = cw - 90, 90
        self.canvas.create_rectangle(lx - 74, ly - 74, lx + 74, ly + 74, outline='#666666', width=1, fill='#ffffff')
        self.canvas.create_image(lx, ly, image=self.tk_loupe, anchor='center')
        self.canvas.create_text(lx, ly + 88, text='局部放大镜', fill='#555555')

    def render_preview(self, _event=None):
        self.canvas.delete('all')
        if self.preview_image is None:
            self.canvas.create_text(200, 120, text='暂无预览', fill='#888888')
            return

        cw = max(120, int(self.canvas.winfo_width() or 800))
        ch = max(120, int(self.canvas.winfo_height() or 600))

        if self.compare_mode.get() and self.repaired_image is not None:
            self._render_compare(cw, ch)
            return

        base_img = self.repaired_image if self.repaired_image is not None else self.preview_image
        ratio = min((cw - 20) / base_img.width, (ch - 20) / base_img.height)
        ratio = max(ratio, 0.01)
        new_size = (max(1, int(base_img.width * ratio)), max(1, int(base_img.height * ratio)))
        self.scale_ratio = ratio

        # ── 底图缓存：尺寸/底图不变就直接复用，避免重复 LANCZOS ──
        if (self._cached_disp is None or
                self._cached_disp_size != new_size or
                self._cached_disp_base is not base_img):
            self._cached_disp = base_img.resize(new_size, Image.Resampling.LANCZOS)
            self._cached_disp_size = new_size
            self._cached_disp_base = base_img

        img = self._cached_disp.copy()

        # ── 蒙版叠加：NEAREST缩放（快），numpy融合 ──
        if self.mask_image is not None and self.repaired_image is None and self.show_mask_overlay.get():
            msk_mode = Image.Resampling.LANCZOS if self.show_feather_preview.get() else Image.Resampling.NEAREST
            mask_small = self.mask_image.resize(new_size, msk_mode)
            try:
                import numpy as np
                img_arr = np.array(img, dtype=np.float32)
                msk_f   = np.array(mask_small, dtype=np.float32) / 255.0
                alpha   = msk_f[:, :, np.newaxis] * 0.45
                img_arr = img_arr * (1 - alpha) + np.array([255, 0, 0], dtype=np.float32) * alpha
                img = Image.fromarray(np.clip(img_arr, 0, 255).astype('uint8'))
            except Exception:
                overlay = Image.new('RGBA', new_size, (255, 0, 0, 0))
                overlay.putalpha(mask_small.point(lambda v: min(120, v)))
                base = img.convert('RGBA')
                base.alpha_composite(overlay)
                img = base.convert('RGB')

        self.tk_preview = ImageTk.PhotoImage(img)
        self.canvas.create_image(cw // 2, ch // 2, image=self.tk_preview, anchor='center')
        self.render_loupe(cw, ch)

    def _render_compare(self, cw, ch):
        half = max(60, cw // 2 - 6)
        ratio = max(min(
            (half - 10) / self.original_image.width,
            (ch - 20)   / self.original_image.height,
        ), 0.01)
        sz = (max(1, int(self.original_image.width * ratio)),
              max(1, int(self.original_image.height * ratio)))
        self.tk_preview_left  = ImageTk.PhotoImage(self.original_image.resize(sz, Image.Resampling.LANCZOS))
        self.tk_preview_right = ImageTk.PhotoImage(self.repaired_image.resize(sz, Image.Resampling.LANCZOS))
        self.canvas.create_image(cw // 4,     ch // 2, image=self.tk_preview_left,  anchor='center')
        self.canvas.create_image(cw * 3 // 4, ch // 2, image=self.tk_preview_right, anchor='center')
        self.canvas.create_line(cw // 2, 10, cw // 2, ch - 10, fill='#999999', dash=(4, 2))
        self.canvas.create_text(cw // 4,     20, text='修复前', fill='#555555')
        self.canvas.create_text(cw * 3 // 4, 20, text='修复后', fill='#555555')
        self.render_loupe(cw, ch)

    def canvas_to_image_xy(self, x, y):
        cw = max(120, int(self.canvas.winfo_width() or 800))
        ch = max(120, int(self.canvas.winfo_height() or 600))
        disp_w = int(self.original_image.width * self.scale_ratio)
        disp_h = int(self.original_image.height * self.scale_ratio)
        ox = (cw - disp_w) // 2
        oy = (ch - disp_h) // 2
        ix = int((x - ox) / max(self.scale_ratio, 1e-6))
        iy = int((y - oy) / max(self.scale_ratio, 1e-6))
        ix = max(0, min(self.original_image.width - 1, ix))
        iy = max(0, min(self.original_image.height - 1, iy))
        return ix, iy

    def _brush_mask_patch(self, radius):
        size = radius * 2 + 1
        mask = Image.new('L', (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size - 1, size - 1), fill=255)
        hardness = max(0, min(100, self.brush_hardness.get()))
        if hardness < 100:
            blur = max(0, int((100 - hardness) / 10))
            if blur > 0:
                mask = mask.filter(ImageFilter.GaussianBlur(radius=blur))
        return mask

    def start_paint(self, event):
        if self.original_image is None or self.mask_image is None:
            return
        self.repaired_image = None
        self.push_undo()
        self.last_x, self.last_y = self.canvas_to_image_xy(event.x, event.y)
        self.last_cx, self.last_cy = event.x, event.y
        self._paint_pil(self.last_x, self.last_y)
        self._draw_brush_canvas(event.x, event.y)
        self.add_history(f'开始{"橡皮擦" if self.tool_mode.get()=="erase" else "涂抹"}')

    def paint_move(self, event):
        if self.original_image is None or self.mask_image is None:
            return
        x, y = self.canvas_to_image_xy(event.x, event.y)
        # 图像坐标插值更新蒙版 + canvas坐标插值绘制笔迹
        steps = max(abs(x - self.last_x), abs(y - self.last_y), 1)
        for i in range(steps + 1):
            t = i / steps
            self._paint_pil(
                int(self.last_x + (x - self.last_x) * t),
                int(self.last_y + (y - self.last_y) * t),
            )
            self._draw_brush_canvas(
                int(self.last_cx + (event.x - self.last_cx) * t),
                int(self.last_cy + (event.y - self.last_cy) * t),
            )
        self.last_x, self.last_y = x, y
        self.last_cx, self.last_cy = event.x, event.y

    def end_paint(self, _event=None):
        self.last_x = self.last_y = None
        self.last_cx = self.last_cy = None
        self.add_history('完成一次笔画')
        self.render_preview()   # ← 松手后才做完整刷新

    def _draw_brush_canvas(self, cx, cy):
        """在 canvas 上即时画半透明圆圈，不碰 PIL，极速响应"""
        r = max(2, int(self.brush_size.get() * self.scale_ratio))
        color = '#4488ff' if self.tool_mode.get() == 'erase' else '#ff3232'
        self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=color, outline='', stipple='gray50',
            tags='brush_stroke',
        )

    def _paint_pil(self, x, y):
        """只更新 PIL 蒙版，不触发 render_preview"""
        radius = self.brush_size.get()
        patch = self._brush_mask_patch(radius)
        box = (x - radius, y - radius)
        if self.tool_mode.get() == 'erase':
            temp = Image.new('L', self.mask_image.size, 0)
            temp.paste(patch, box)
            self.mask_image = ImageChops.subtract(self.mask_image, temp)
        else:
            self.mask_image.paste(255, box=box, mask=patch)

    # 保留旧名称兼容其他调用处
    def paint_at(self, x, y):
        self._paint_pil(x, y)

    def paint_line(self, x1, y1, x2, y2):
        if x1 is None or y1 is None:
            self._paint_pil(x2, y2)
            return
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for i in range(steps + 1):
            t = i / steps
            self._paint_pil(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))

    def clear_mask(self):
        if self.original_image is None:
            return
        self.mask_image = Image.new('L', self.original_image.size, 0)
        self.preview_image = self.original_image.copy()
        self.repaired_image = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.add_history('清空涂抹蒙版')
        self.render_preview()

    def repair_image(self):
        if self.original_image is None or self.mask_image is None:
            return None
        if HAS_CV2:
            img = np.array(self.original_image.convert('RGB'))
            mask = np.array(self.mask_image)
            radius = max(1, int(self.strength.get()))
            result = cv2.inpaint(img, mask, radius, cv2.INPAINT_TELEA)
            return Image.fromarray(result)
        blurred = self.original_image.filter(ImageFilter.GaussianBlur(radius=max(1, self.strength.get())))
        out = self.original_image.copy()
        out.paste(blurred, mask=self.mask_image)
        return out

    def preview_repair(self):
        result = self.repair_image()
        if result is None:
            messagebox.showwarning('提示', '请先加载图片并涂抹需要修复的区域')
            return
        self.repaired_image = result
        self.preview_image = result
        self.add_history('生成修复预览')
        self.render_preview()
        self.info_label.configure(text='已生成修复预览。可切换“修复前后分屏对比”查看效果。')

    def _save_result_now(self):
        result = self.repair_image()
        if result is None:
            messagebox.showwarning('提示', '请先加载图片并涂抹需要修复的区域')
            return
        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        output_base.mkdir(parents=True, exist_ok=True)
        src = Path(self.input_path.get())
        name = f'{src.stem}_retouched.{self.output_format.get()}'
        out_path = output_base / name

        progress = self.create_progress_window('涂抹修复处理中...', 1)
        progress.output_dir = str(output_base)
        self.update_progress(progress, 0, 1, src.name)
        saved = save_image_by_format(result, out_path, self.output_format.get())
        self.add_history(f'保存修复结果：{saved.name}')
        self.finish_processing(progress, 1, [], '普通涂抹修复', f'输出文件: {saved.name}')

    def save_repair(self):
        result = self.repair_image()
        if result is None:
            messagebox.showwarning('提示', '请先加载图片并涂抹需要修复的区域')
            return
        before_img = self.original_image.copy() if self.original_image is not None else result
        after_img = result.copy()
        SaveCompareDialog(self.parent_frame, before_img, after_img, self._save_result_now)
