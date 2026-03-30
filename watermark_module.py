import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox
from pathlib import Path
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter
import ttkbootstrap as tb
from ttkbootstrap.constants import *

from common_utils import (
    DATA_DIR, ImagePreview, PreviewUpdater, bind_drop_to_widget, create_input_row, create_output_row,
    default_output_dir, list_images, open_image_with_exif, make_card, make_primary_button, make_secondary_button,
    read_json, save_image_by_format, write_json
)


POSITION_MAP = {
    '左上': 'top_left',
    '顶部居中': 'top_center',
    '右上': 'top_right',
    '左侧居中': 'center_left',
    '正中间': 'center',
    '右侧居中': 'center_right',
    '左下': 'bottom_left',
    '底部居中': 'bottom_center',
    '右下': 'bottom_right',
}


class WatermarkModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing

        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.exclude_dir = tk.StringVar()
        self.include_subdirs = tk.BooleanVar(value=True)
        self.independent_folder = tk.BooleanVar(value=False)
        self.output_format = tk.StringVar(value='original')
        self.watermark_mode = tk.StringVar(value='timestamp')
        self.watermark_text = tk.StringVar(value='')
        self.batch_count = tk.IntVar(value=1)
        self.timestamp_offset_ms = tk.IntVar(value=10)
        self.opacity_percent = tk.IntVar(value=5)
        self.position_cn = tk.StringVar(value='右下')
        self.font_size = tk.IntVar(value=36)
        self.blend_multiply = tk.BooleanVar(value=False)
        self.use_manual_position = tk.BooleanVar(value=False)
        self.manual_x_ratio = tk.DoubleVar(value=0.0)
        self.manual_y_ratio = tk.DoubleVar(value=0.0)
        self.watermark_color = '#FFFFFF'

        self._preview_updater = None
        self._dragging_watermark = False
        self._drag_offset_x = 0.0
        self._drag_offset_y = 0.0
        self._last_preview_source = None
        self._last_preview_result = None
        self._last_preview_text = ''
        self._last_watermark_box = None
        self._last_canvas_box = None
        self._last_canvas_ratio = 1.0
        self._last_canvas_image_origin = (0, 0)
        self._drag_refresh_job = None

        self.input_path.trace_add('write', self.on_input_changed)
        self.preset_file = DATA_DIR / 'watermark_presets.json'
        self.create_ui()
        self.on_input_changed()
        self.update_mode_state()

    def create_ui(self):
        body = tb.Frame(self.parent_frame)
        body.pack(fill=BOTH, expand=YES)
        left = tb.Frame(body)
        left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 12))
        right = tb.Frame(body)
        right.pack(side=RIGHT, fill=Y)

        dirs = tb.LabelFrame(left, text='输入输出', padding=12)
        dirs.pack(fill=X, pady=(0, 10))
        self.input_entry = create_input_row(dirs, '输入路径:', self.input_path)
        create_output_row(dirs, '输出目录:', self.output_dir)

        row = tb.Frame(dirs)
        row.pack(fill=X, pady=5)
        tb.Label(row, text='排除目录:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(row, textvariable=self.exclude_dir).pack(side=LEFT, fill=X, expand=YES, padx=5)
        tb.Button(row, text='浏览', command=self.pick_exclude, bootstyle='secondary-outline').pack(side=LEFT)
        tb.Button(row, text='清除', command=lambda: self.exclude_dir.set(''), bootstyle='secondary-outline').pack(side=LEFT, padx=(4, 0))

        opts = tb.LabelFrame(left, text='处理选项', padding=12)
        opts.pack(fill=X, pady=(0, 10))
        tb.Checkbutton(opts, text='包含子目录', variable=self.include_subdirs, bootstyle='round-toggle', command=self.on_input_changed).pack(anchor=W)
        tb.Checkbutton(opts, text='输出到独立文件夹', variable=self.independent_folder, bootstyle='round-toggle').pack(anchor=W, pady=(6, 0))

        fmt = tb.Frame(opts)
        fmt.pack(fill=X, pady=(8, 0))
        tb.Label(fmt, text='输出格式:').pack(side=LEFT, padx=(0, 12))
        for label, value in [('保持原格式', 'original'), ('JPG', 'jpg'), ('PNG', 'png'), ('WEBP', 'webp')]:
            tb.Radiobutton(fmt, text=label, variable=self.output_format, value=value, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        wm = tb.LabelFrame(left, text='水印设置', padding=12)
        wm.pack(fill=X, pady=(0, 10))

        mode = tb.Frame(wm)
        mode.pack(fill=X, pady=4)
        tb.Label(mode, text='水印类型:', width=10, anchor=W).pack(side=LEFT)
        tb.Radiobutton(mode, text='时间戳', variable=self.watermark_mode, value='timestamp', bootstyle='toolbutton-outline', command=self.update_mode_state).pack(side=LEFT, padx=3)
        tb.Radiobutton(mode, text='自定义文字', variable=self.watermark_mode, value='custom', bootstyle='toolbutton-outline', command=self.update_mode_state).pack(side=LEFT, padx=3)

        self.text_row = tb.Frame(wm)
        tb.Label(self.text_row, text='水印文字:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(self.text_row, textvariable=self.watermark_text).pack(side=LEFT, fill=X, expand=YES)

        self.batch_row = tb.Frame(wm)
        self.batch_row.pack(fill=X, pady=4)
        tb.Label(self.batch_row, text='批量数量:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(self.batch_row, textvariable=self.batch_count, width=10).pack(side=LEFT)
        tb.Label(self.batch_row, text='偏移毫秒:', width=10, anchor=W).pack(side=LEFT, padx=(20, 0))
        tb.Entry(self.batch_row, textvariable=self.timestamp_offset_ms, width=10).pack(side=LEFT)

        fs = tb.Frame(wm)
        fs.pack(fill=X, pady=4)
        tb.Label(fs, text='字体大小:', width=10, anchor=W).pack(side=LEFT)
        tb.Scale(fs, from_=10, to=200, variable=self.font_size, orient=HORIZONTAL, bootstyle='info').pack(side=LEFT, fill=X, expand=YES, padx=(0, 10))
        self.font_label = tb.Label(fs, text=f'{self.font_size.get()} px', width=10)
        self.font_label.pack(side=LEFT)
        self.font_size.trace_add('write', lambda *_: self.font_label.config(text=f'{self.font_size.get()} px'))

        op = tb.Frame(wm)
        op.pack(fill=X, pady=4)
        tb.Label(op, text='透明度:', width=10, anchor=W).pack(side=LEFT)
        tb.Scale(op, from_=0, to=100, variable=self.opacity_percent, orient=HORIZONTAL, bootstyle='success').pack(side=LEFT, fill=X, expand=YES, padx=(0, 10))
        self.opacity_label = tb.Label(op, text=f'{self.opacity_percent.get()}%', width=10)
        self.opacity_label.pack(side=LEFT)
        self.opacity_percent.trace_add('write', lambda *_: self.opacity_label.config(text=f'{self.opacity_percent.get()}%'))

        pos = tb.Frame(wm)
        pos.pack(fill=X, pady=4)
        tb.Label(pos, text='水印位置:', width=10, anchor=W).pack(side=LEFT)
        combo = tb.Combobox(pos, textvariable=self.position_cn, values=list(POSITION_MAP.keys()), state='readonly', width=14)
        combo.pack(side=LEFT)
        combo.bind('<<ComboboxSelected>>', self.on_position_preset_changed)
        tb.Button(pos, text='重置拖放', command=self.reset_manual_position, bootstyle='secondary-outline').pack(side=LEFT, padx=(8, 0))

        color_row = tb.Frame(wm)
        color_row.pack(fill=X, pady=4)
        tb.Label(color_row, text='文字颜色:', width=10, anchor=W).pack(side=LEFT)
        tb.Button(color_row, text='选择颜色', command=self.choose_color, bootstyle='primary-outline').pack(side=LEFT)
        self.color_preview = tk.Frame(color_row, width=36, height=24, bg=self.watermark_color, relief='solid', borderwidth=1)
        self.color_preview.pack(side=LEFT, padx=8)
        self.color_preview.pack_propagate(False)
        tb.Checkbutton(color_row, text='正片叠底', variable=self.blend_multiply, bootstyle='round-toggle').pack(side=LEFT, padx=(8, 0))

        hint_row = tb.Frame(wm)
        hint_row.pack(fill=X, pady=(4, 0))
        self.drag_hint_label = tb.Label(hint_row, text='提示：可在右侧结果预览中直接拖动水印到自定义位置。', bootstyle='secondary', wraplength=420, justify=LEFT)
        self.drag_hint_label.pack(anchor=W)

        action_card, preset_row = make_card(left, '快捷操作', '模板与执行操作统一放在这里')
        make_secondary_button(preset_row, '保存模板', self.save_preset).pack(side=LEFT)
        make_secondary_button(preset_row, '载入模板', self.load_preset).pack(side=LEFT, padx=6)
        make_primary_button(left, '开始处理', self.process_watermark).pack(pady=8)

        self.preview = ImagePreview(right, '图片预览')
        self._preview_updater = PreviewUpdater(
            self.parent_frame,
            self.preview,
            self._get_preview_source_image,
            self._render_preview_result,
            delay_ms=250
        )
        for var in [
            self.watermark_mode, self.watermark_text, self.batch_count, self.timestamp_offset_ms,
            self.opacity_percent, self.position_cn, self.font_size, self.blend_multiply,
            self.use_manual_position, self.manual_x_ratio, self.manual_y_ratio
        ]:
            try:
                var.trace_add('write', self._preview_updater.trigger)
            except Exception:
                pass
        bind_drop_to_widget(self.input_entry, self.handle_drop, accept='any')
        bind_drop_to_widget(self.parent_frame, self.handle_drop, accept='any')
        self.bind_preview_drag_events()

    def bind_preview_drag_events(self):
        canvas = self.preview.canvas_right
        canvas.bind('<ButtonPress-1>', self.on_preview_press, add='+')
        canvas.bind('<B1-Motion>', self.on_preview_drag, add='+')
        canvas.bind('<ButtonRelease-1>', self.on_preview_release, add='+')

    def _get_preview_source_image(self):
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            return open_image_with_exif(p)
        if p.exists() and p.is_dir():
            imgs = self.get_images()
            if imgs:
                return open_image_with_exif(imgs[0][0])
        return None

    def _render_preview_result(self, img):
        text = self.build_watermark_text(0)
        self._last_preview_text = text
        result = self.add_watermark(img, text)
        self._last_preview_source = img.copy()
        self._last_preview_result = result.copy()
        self.parent_frame.after_idle(self.render_watermark_overlay)
        return result

    def update_mode_state(self):
        if self.watermark_mode.get() == 'custom':
            if not self.text_row.winfo_manager():
                self.text_row.pack(fill=X, pady=4, before=self.batch_row)
            if self.batch_row.winfo_manager():
                self.batch_row.pack_forget()
        else:
            if self.text_row.winfo_manager():
                self.text_row.pack_forget()
            if not self.batch_row.winfo_manager():
                self.batch_row.pack(fill=X, pady=4, before=self.font_label.master)
        if self._preview_updater:
            self._preview_updater.trigger()

    def on_input_changed(self, *_):
        self.output_dir.set(default_output_dir(self.input_path.get()))
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            self.preview.show(str(p))
        elif p.exists() and p.is_dir():
            imgs = list_images(p, self.include_subdirs.get())
            if imgs:
                self.preview.show_folder_preview(str(p), image_count=len(imgs), include_subdirs=self.include_subdirs.get())
            else:
                self.preview.clear('文件夹内没有可预览的图片')
        else:
            self.preview.clear()
        if self._preview_updater:
            self._preview_updater.trigger()

    def handle_drop(self, path):
        self.input_path.set(path)
        self.on_input_changed()

    def pick_exclude(self):
        d = filedialog.askdirectory(title='选择排除目录')
        if d:
            self.exclude_dir.set(d)

    def save_preset(self):
        presets = read_json(self.preset_file, [])
        presets.append({
            'mode': self.watermark_mode.get(),
            'text': self.watermark_text.get(),
            'batch': self.batch_count.get(),
            'offset': self.timestamp_offset_ms.get(),
            'opacity': self.opacity_percent.get(),
            'position': self.position_cn.get(),
            'font_size': self.font_size.get(),
            'color': self.watermark_color,
            'output_format': self.output_format.get(),
            'blend_multiply': self.blend_multiply.get(),
            'use_manual_position': self.use_manual_position.get(),
            'manual_x_ratio': self.manual_x_ratio.get(),
            'manual_y_ratio': self.manual_y_ratio.get(),
        })
        write_json(self.preset_file, presets)
        messagebox.showinfo('提示', '水印模板已保存')

    def load_preset(self):
        presets = read_json(self.preset_file, [])
        if not presets:
            messagebox.showwarning('提示', '还没有保存的模板')
            return
        p = presets[-1]
        self.watermark_mode.set(p.get('mode', 'timestamp'))
        self.watermark_text.set(p.get('text', ''))
        self.batch_count.set(p.get('batch', 1))
        self.timestamp_offset_ms.set(p.get('offset', 10))
        self.opacity_percent.set(p.get('opacity', 5))
        self.position_cn.set(p.get('position', '右下'))
        self.font_size.set(p.get('font_size', 36))
        self.watermark_color = p.get('color', '#FFFFFF')
        self.color_preview.config(bg=self.watermark_color)
        self.output_format.set(p.get('output_format', 'original'))
        self.blend_multiply.set(p.get('blend_multiply', False))
        self.use_manual_position.set(p.get('use_manual_position', False))
        self.manual_x_ratio.set(p.get('manual_x_ratio', 0.0))
        self.manual_y_ratio.set(p.get('manual_y_ratio', 0.0))
        self.update_drag_hint()
        self.update_mode_state()
        if self._preview_updater:
            self._preview_updater.trigger()

    def choose_color(self):
        color = colorchooser.askcolor(initialcolor=self.watermark_color)[1]
        if color:
            self.watermark_color = color
            self.color_preview.configure(bg=color)
            if self._preview_updater:
                self._preview_updater.trigger()

    def on_position_preset_changed(self, _event=None):
        self.use_manual_position.set(False)
        self.update_drag_hint()
        if self._preview_updater:
            self._preview_updater.trigger()

    def reset_manual_position(self):
        self.use_manual_position.set(False)
        self.manual_x_ratio.set(0.0)
        self.manual_y_ratio.set(0.0)
        self.update_drag_hint()
        if self._preview_updater:
            self._preview_updater.trigger()

    def update_drag_hint(self):
        if self.use_manual_position.get():
            self.drag_hint_label.configure(text='当前：已启用手动拖放位置，可继续在右侧结果预览中拖动微调。')
        else:
            self.drag_hint_label.configure(text='提示：可在右侧结果预览中直接拖动水印到自定义位置。')

    def get_images(self):
        input_path = Path(self.input_path.get())
        exclude_path = Path(self.exclude_dir.get()) if self.exclude_dir.get() else None
        return list_images(input_path, self.include_subdirs.get(), exclude_path)

    def build_watermark_text(self, batch_index):
        if self.watermark_mode.get() == 'custom':
            return self.watermark_text.get().strip()
        base = datetime.now() + timedelta(milliseconds=(batch_index * self.timestamp_offset_ms.get()))
        return str(int(base.timestamp() * 1000))

    def get_font(self, size):
        candidates = [
            r'C:\Windows\Fonts\msyh.ttc',
            r'C:\Windows\Fonts\msyhbd.ttc',
            r'C:\Windows\Fonts\simhei.ttf',
            r'C:\Windows\Fonts\simsun.ttc',
            r'C:\Windows\Fonts\arial.ttf',
        ]
        for font_path in candidates:
            try:
                if Path(font_path).exists():
                    return ImageFont.truetype(font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _parse_rgb(self, value):
        return tuple(int(value.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))

    def get_text_metrics(self, text):
        font = self.get_font(self.font_size.get())
        probe = Image.new('RGBA', (16, 16), (255, 255, 255, 0))
        draw = ImageDraw.Draw(probe)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = max(1, bbox[2] - bbox[0])
        text_h = max(1, bbox[3] - bbox[1])
        return font, bbox, text_w, text_h

    def get_watermark_position(self, img, text_w, text_h):
        margin = 20
        max_x = max(0, img.width - text_w - margin)
        max_y = max(0, img.height - text_h - margin)

        if self.use_manual_position.get():
            x = int(round(self.manual_x_ratio.get() * max(1, img.width - text_w)))
            y = int(round(self.manual_y_ratio.get() * max(1, img.height - text_h)))
            return max(0, min(x, img.width - text_w)), max(0, min(y, img.height - text_h))

        pos_key = POSITION_MAP.get(self.position_cn.get(), 'bottom_right')
        mapping = {
            'top_left': (margin, margin),
            'top_center': ((img.width - text_w) // 2, margin),
            'top_right': (img.width - text_w - margin, margin),
            'center_left': (margin, (img.height - text_h) // 2),
            'center': ((img.width - text_w) // 2, (img.height - text_h) // 2),
            'center_right': (img.width - text_w - margin, (img.height - text_h) // 2),
            'bottom_left': (margin, img.height - text_h - margin),
            'bottom_center': ((img.width - text_w) // 2, img.height - text_h - margin),
            'bottom_right': (img.width - text_w - margin, img.height - text_h - margin),
        }
        x, y = mapping[pos_key]
        return max(0, min(x, img.width - text_w)), max(0, min(y, img.height - text_h))

    def update_manual_position_from_xy(self, img, text_w, text_h, x, y):
        max_x = max(0, img.width - text_w)
        max_y = max(0, img.height - text_h)
        x = max(0, min(int(round(x)), max_x))
        y = max(0, min(int(round(y)), max_y))
        self.use_manual_position.set(True)
        self.manual_x_ratio.set(0.0 if max_x == 0 else x / max_x)
        self.manual_y_ratio.set(0.0 if max_y == 0 else y / max_y)
        self.update_drag_hint()
        return x, y

    def refresh_preview_during_drag(self):
        if self._last_preview_source is None or not self._last_preview_text:
            return
        try:
            result = self.add_watermark(self._last_preview_source, self._last_preview_text)
            self._last_preview_result = result.copy()
            self.preview.update_right_image(result)
            self.render_watermark_overlay()
        except Exception:
            if self._preview_updater:
                self._preview_updater.trigger()

    def render_watermark_overlay(self):
        canvas = self.preview.canvas_right
        canvas.delete('wm_overlay')
        img = self._last_preview_result
        text = self._last_preview_text
        if img is None or not text:
            return

        try:
            font, _bbox, text_w, text_h = self.get_text_metrics(text)
            x, y = self.get_watermark_position(img, text_w, text_h)
            self._last_watermark_box = (x, y, text_w, text_h)

            cw = max(120, int(canvas.winfo_width() or 420))
            ch = max(120, int(canvas.winfo_height() or 420))
            if self.preview.zoom_mode.get() == 'fit':
                avail_w = max(40, cw - 24)
                avail_h = max(40, ch - 24)
                ratio = min(avail_w / max(1, img.width), avail_h / max(1, img.height))
            elif self.preview.zoom_mode.get() == 'actual':
                ratio = 1.0
            else:
                ratio = self.preview.manual_zoom
            ratio = max(0.05, min(8.0, ratio))

            render_w = max(1, int(img.width * ratio))
            render_h = max(1, int(img.height * ratio))
            pan = self.preview._pan_state['right']
            center_x = (cw // 2) + pan['x']
            center_y = (ch // 2) + pan['y']
            image_x0 = center_x - render_w // 2
            image_y0 = center_y - render_h // 2
            self._last_canvas_ratio = ratio
            self._last_canvas_image_origin = (image_x0, image_y0)

            x0 = image_x0 + (x * ratio)
            y0 = image_y0 + (y * ratio)
            x1 = image_x0 + ((x + text_w) * ratio)
            y1 = image_y0 + ((y + text_h) * ratio)
            self._last_canvas_box = (x0, y0, x1, y1)

            canvas.create_rectangle(x0, y0, x1, y1, outline='#00d1ff', width=2, dash=(6, 3), tags='wm_overlay')
            canvas.create_rectangle(x1 - 8, y1 - 8, x1 + 8, y1 + 8, outline='#00d1ff', fill='#00d1ff', tags='wm_overlay')
            status = '手动拖放' if self.use_manual_position.get() else f'预设位置：{self.position_cn.get()}'
            blend = '正片叠底' if self.blend_multiply.get() else '普通叠加'
            canvas.create_text(x0, max(14, y0 - 12), text=f'{status} | {blend}', anchor='w', fill='#00d1ff', tags='wm_overlay')
        except Exception:
            pass

    def on_preview_press(self, event):
        box = self._last_canvas_box
        if not box or self._last_preview_result is None or self._last_watermark_box is None:
            return
        x0, y0, x1, y1 = box
        hit_padding = 10
        if (x0 - hit_padding) <= event.x <= (x1 + hit_padding) and (y0 - hit_padding) <= event.y <= (y1 + hit_padding):
            ratio = self._last_canvas_ratio or 1.0
            image_x0, image_y0 = self._last_canvas_image_origin
            wm_x, wm_y, _wm_w, _wm_h = self._last_watermark_box
            pointer_img_x = (event.x - image_x0) / ratio
            pointer_img_y = (event.y - image_y0) / ratio
            self._drag_offset_x = pointer_img_x - wm_x
            self._drag_offset_y = pointer_img_y - wm_y
            self._dragging_watermark = True
            return 'break'

    def on_preview_drag(self, event):
        if not self._dragging_watermark or self._last_preview_result is None or not self._last_preview_text:
            return
        _font, _bbox, text_w, text_h = self.get_text_metrics(self._last_preview_text)
        ratio = self._last_canvas_ratio or 1.0
        image_x0, image_y0 = self._last_canvas_image_origin
        pointer_img_x = (event.x - image_x0) / ratio
        pointer_img_y = (event.y - image_y0) / ratio
        new_x = pointer_img_x - self._drag_offset_x
        new_y = pointer_img_y - self._drag_offset_y
        self.update_manual_position_from_xy(self._last_preview_result, text_w, text_h, new_x, new_y)
        if self._drag_refresh_job:
            try:
                self.parent_frame.after_cancel(self._drag_refresh_job)
            except Exception:
                pass
            self._drag_refresh_job = None
        self._drag_refresh_job = self.parent_frame.after(16, self.refresh_preview_during_drag)
        return 'break'

    def on_preview_release(self, event):
        if self._dragging_watermark:
            self._dragging_watermark = False
            if self._drag_refresh_job:
                try:
                    self.parent_frame.after_cancel(self._drag_refresh_job)
                except Exception:
                    pass
                self._drag_refresh_job = None
            self.refresh_preview_during_drag()
            return 'break'

    def _estimate_local_brightness(self, base_rgb, x, y, text_w, text_h):
        sample_pad_x = max(6, int(text_w * 0.10))
        sample_pad_y = max(6, int(text_h * 0.18))
        sx0 = max(0, x - sample_pad_x)
        sy0 = max(0, y - sample_pad_y)
        sx1 = min(base_rgb.width, x + text_w + sample_pad_x)
        sy1 = min(base_rgb.height, y + text_h + sample_pad_y)
        region = base_rgb.crop((sx0, sy0, sx1, sy1)).convert('L')
        hist = region.histogram()
        total = sum(hist) or 1
        weighted = sum(i * count for i, count in enumerate(hist))
        return weighted / total / 255.0

    def _build_adaptive_multiply_params(self, base_rgb, x, y, text_w, text_h, opacity_ratio):
        brightness = self._estimate_local_brightness(base_rgb, x, y, text_w, text_h)
        darkness = 1.0 - brightness
        user_strength = max(0.015, min(0.12, opacity_ratio * 0.36))

        # 亮背景可以稍微加重一点，暗背景进一步压低存在感。
        adaptive_strength = user_strength * (0.58 + brightness * 0.92)
        adaptive_strength *= (1.0 - darkness * 0.28)
        adaptive_strength = max(0.010, min(0.115, adaptive_strength))

        blur_radius = max(0.8, min(2.8, self.font_size.get() / 44 + darkness * 0.9))
        mask_alpha = max(5, min(36, int(255 * adaptive_strength * (0.58 + brightness * 0.25))))
        return brightness, adaptive_strength, blur_radius, mask_alpha

    def add_watermark(self, img, text):
        base = img.convert('RGBA') if img.mode != 'RGBA' else img.copy()
        font, _bbox, text_w, text_h = self.get_text_metrics(text)
        x, y = self.get_watermark_position(base, text_w, text_h)
        r, g, b = self._parse_rgb(self.watermark_color)
        opacity_ratio = max(0.0, min(1.0, self.opacity_percent.get() / 100.0))
        alpha = int(255 * opacity_ratio)
        shadow_alpha = max(22, min(92, int(alpha * 0.45)))

        if self.blend_multiply.get():
            base_rgb = base.convert('RGB')
            multiply_rgb = Image.new('RGB', base.size, (255, 255, 255))
            mask = Image.new('L', base.size, 0)
            draw_rgb = ImageDraw.Draw(multiply_rgb)
            draw_mask = ImageDraw.Draw(mask)

            brightness, adaptive_strength, blur_radius, mask_alpha = self._build_adaptive_multiply_params(
                base_rgb, x, y, text_w, text_h, opacity_ratio
            )

            mix_to_white = 1.0 - adaptive_strength
            subtle_color = (
                int(255 * mix_to_white + r * adaptive_strength),
                int(255 * mix_to_white + g * adaptive_strength),
                int(255 * mix_to_white + b * adaptive_strength),
            )

            draw_rgb.text((x, y), text, font=font, fill=subtle_color)
            draw_mask.text((x, y), text, font=font, fill=mask_alpha)

            # 再叠一层更淡的软边，让单水印融进原图，不容易看出轮廓。
            edge_shift = max(1, int(self.font_size.get() * 0.018))
            edge_alpha = max(2, int(mask_alpha * (0.18 + brightness * 0.12)))
            draw_mask.text((x + edge_shift, y + edge_shift), text, font=font, fill=edge_alpha)

            mask = mask.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            multiplied = ImageChops.multiply(base_rgb, multiply_rgb)
            result_rgb = Image.composite(multiplied, base_rgb, mask)
            return result_rgb.convert('RGBA')

        layer = Image.new('RGBA', base.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(layer)
        draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, shadow_alpha))
        draw.text((x, y), text, font=font, fill=(r, g, b, alpha))
        return Image.alpha_composite(base, layer)

    def process_watermark(self):
        if not self.input_path.get():
            messagebox.showerror('错误', '请选择图片文件或文件夹')
            return
        if self.watermark_mode.get() == 'custom' and not self.watermark_text.get().strip():
            messagebox.showerror('错误', '请输入水印文字')
            return
        input_path = Path(self.input_path.get())
        if not input_path.exists():
            messagebox.showerror('错误', '输入路径不存在')
            return
        images = self.get_images()
        if not images:
            messagebox.showwarning('提示', '没有找到图片')
            return

        batch_total = max(1, self.batch_count.get())
        total_jobs = len(images) * batch_total
        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        progress = self.create_progress_window('水印处理中...', total_jobs)
        progress.output_dir = str(output_base)
        processed, failed = 0, []
        preview_before = None
        preview_after = None

        for batch in range(batch_total):
            text = self.build_watermark_text(batch)
            batch_dir = output_base / f'方案{batch + 1:02d}' if self.independent_folder.get() or batch_total > 1 else output_base
            for i, (img_path, rel_path) in enumerate(images):
                index = batch * len(images) + i
                try:
                    self.update_progress(progress, index, total_jobs, str(rel_path))
                    img = open_image_with_exif(img_path)
                    watermarked = self.add_watermark(img, text)
                    saved_path = save_image_by_format(watermarked, batch_dir / rel_path, self.output_format.get())
                    if preview_before is None:
                        preview_before = str(img_path)
                    preview_after = str(saved_path)
                    processed += 1
                except Exception as e:
                    failed.append(f'{rel_path} - {e}')

        mode_text = '时间戳' if self.watermark_mode.get() == 'timestamp' else '自定义文字'
        position_text = '手动拖放' if self.use_manual_position.get() else self.position_cn.get()
        blend_text = '正片叠底' if self.blend_multiply.get() else '普通叠加'
        extra = (
            f'模式: {mode_text}\n'
            f'批量数量: {batch_total}\n'
            f'位置: {position_text}\n'
            f'混合模式: {blend_text}\n'
            f'独立文件夹: {"是" if self.independent_folder.get() else "否"}'
        )
        if preview_before and preview_after:
            self.preview.show_dual(preview_before, preview_after, prefix_text='原图 / 水印结果')
        self.finish_processing(progress, processed, failed, '水印处理', extra)