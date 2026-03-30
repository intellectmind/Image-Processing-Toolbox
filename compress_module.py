import io
import os
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from PIL import Image
import ttkbootstrap as tb
from ttkbootstrap.constants import *

from common_utils import (
    ImagePreview, PreviewUpdater, bind_drop_to_widget, create_input_row, create_output_row,
    default_output_dir, latest_module_preset, load_module_presets, list_images, open_image_with_exif, PresetPickerDialog, make_card, make_primary_button, make_secondary_button, save_module_preset
)


class CompressModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing

        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.include_subdirs = tk.BooleanVar(value=True)
        self.independent_folder = tk.BooleanVar(value=False)
        self.target_size = tk.DoubleVar(value=0.3)
        self.target_unit = tk.StringVar(value='MB')
        self.min_quality = tk.IntVar(value=35)
        self.max_quality = tk.IntVar(value=92)
        self.output_format = tk.StringVar(value='jpg')
        self.allow_resize = tk.BooleanVar(value=False)
        self.retry_strategy = tk.BooleanVar(value=True)
        self.max_width = tk.IntVar(value=2560)
        self.max_height = tk.IntVar(value=2560)

        self.input_path.trace_add('write', self.on_input_changed)
        self._preview_updater = None
        self.preset_module_name = 'compress'
        self.create_ui()
        self.on_input_changed()

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
        tb.Checkbutton(dirs, text='包含子目录', variable=self.include_subdirs, bootstyle='round-toggle').pack(anchor=W, pady=(6,0))
        tb.Checkbutton(dirs, text='输出到独立文件夹', variable=self.independent_folder, bootstyle='round-toggle').pack(anchor=W)

        cfg, cfg_inner = make_card(left, '压缩设置', '设置目标体积、质量范围和压缩策略')
        r1 = tb.Frame(cfg); r1.pack(fill=X, pady=5)
        tb.Label(r1, text='目标体积:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(r1, textvariable=self.target_size, width=10).pack(side=LEFT)
        tb.Combobox(r1, textvariable=self.target_unit, values=['KB', 'MB'], width=8, state='readonly').pack(side=LEFT, padx=(6,20))
        tb.Label(r1, text='输出格式:').pack(side=LEFT, padx=(0,8))
        for label, value in [('JPG','jpg'), ('WEBP','webp'), ('PNG','png')]:
            tb.Radiobutton(r1, text=label, variable=self.output_format, value=value, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        r2 = tb.Frame(cfg); r2.pack(fill=X, pady=5)
        tb.Label(r2, text='质量范围:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(r2, textvariable=self.min_quality, width=8).pack(side=LEFT)
        tb.Label(r2, text='到').pack(side=LEFT, padx=4)
        tb.Entry(r2, textvariable=self.max_quality, width=8).pack(side=LEFT)
        tb.Checkbutton(r2, text='失败重试策略', variable=self.retry_strategy, bootstyle='round-toggle').pack(side=LEFT, padx=(20, 0))

        r3 = tb.Frame(cfg); r3.pack(fill=X, pady=5)
        tb.Checkbutton(r3, text='允许缩小分辨率', variable=self.allow_resize, bootstyle='round-toggle').pack(side=LEFT)
        tb.Label(r3, text='最大宽:').pack(side=LEFT, padx=(20, 6))
        tb.Entry(r3, textvariable=self.max_width, width=8).pack(side=LEFT)
        tb.Label(r3, text='最大高:').pack(side=LEFT, padx=(15, 6))
        tb.Entry(r3, textvariable=self.max_height, width=8).pack(side=LEFT)

        action_card, preset_row = make_card(left, '快捷操作', '模板与执行操作统一放在这里')
        preset_row.pack(fill=X, pady=(0, 8))
        make_secondary_button(preset_row, '保存模板', self.save_preset).pack(side=LEFT)
        make_secondary_button(preset_row, '载入模板', self.load_preset).pack(side=LEFT, padx=6)
        make_primary_button(left, '开始压缩', self.process_compress).pack(pady=8)

        self.preview = ImagePreview(right, '图片预览')
        self._preview_updater = PreviewUpdater(
            self.parent_frame,
            self.preview,
            self._get_preview_source_image,
            self._render_preview_result,
            delay_ms=300
        )
        for var in [self.target_size, self.target_unit, self.min_quality, self.max_quality,
                    self.output_format, self.allow_resize, self.max_width, self.max_height]:
            try:
                var.trace_add('write', self._preview_updater.trigger)
            except Exception:
                pass
        bind_drop_to_widget(self.input_entry, self.handle_drop, accept='any')
        bind_drop_to_widget(self.parent_frame, self.handle_drop, accept='any')


    def _get_preview_source_image(self):
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            return open_image_with_exif(p)
        if p.exists() and p.is_dir():
            imgs = list_images(p, self.include_subdirs.get())
            if imgs:
                return open_image_with_exif(imgs[0][0])
        return None

    def _render_preview_result(self, img):
        data, fmt = self.compress_one(img)
        import io
        return Image.open(io.BytesIO(data)).copy()

    def on_input_changed(self, *_):
        self.output_dir.set(default_output_dir(self.input_path.get()))
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            self.preview.show(str(p))
        elif p.exists() and p.is_dir():
            imgs = list_images(p, self.include_subdirs.get())
            self.preview.show(str(imgs[0][0])) if imgs else self.preview.clear()
        else:
            self.preview.clear()
        if self._preview_updater:
            self._preview_updater.trigger()

    def handle_drop(self, path):
        self.input_path.set(path)
        self.on_input_changed()

    def _target_bytes(self):
        size = max(1.0, self.target_size.get())
        return int(size * 1024 * 1024) if self.target_unit.get() == 'MB' else int(size * 1024)

    def _encode_to_bytes(self, img, fmt, quality):
        bio = io.BytesIO()
        if fmt == 'jpg':
            if img.mode == 'RGBA':
                bg = Image.new('RGB', img.size, (255,255,255))
                bg.paste(img, mask=img.getchannel('A'))
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(bio, 'JPEG', quality=quality, optimize=True)
        elif fmt == 'webp':
            img.save(bio, 'WEBP', quality=quality, method=6)
        else:
            img.save(bio, 'PNG', optimize=True, compress_level=9)
        return bio.getvalue()

    def compress_one(self, img):
        target = self._target_bytes()
        fmt = self.output_format.get()
        work = img.copy()
        if self.allow_resize.get():
            work.thumbnail((self.max_width.get(), self.max_height.get()), Image.Resampling.LANCZOS)

        best = None
        for q in range(self.max_quality.get(), self.min_quality.get()-1, -4):
            data = self._encode_to_bytes(work, fmt, q)
            best = data
            if len(data) <= target:
                return data, fmt
        if self.retry_strategy.get() and self.allow_resize.get():
            for scale in [0.9, 0.8, 0.7, 0.6]:
                small = work.resize((max(1, int(work.width*scale)), max(1, int(work.height*scale))), Image.Resampling.LANCZOS)
                for q in range(self.max_quality.get(), self.min_quality.get()-1, -6):
                    data = self._encode_to_bytes(small, fmt, q)
                    best = data
                    if len(data) <= target:
                        return data, fmt
            if fmt != 'jpg':
                fmt = 'jpg'
                for scale in [1.0, 0.85, 0.7]:
                    small = work.resize((max(1, int(work.width*scale)), max(1, int(work.height*scale))), Image.Resampling.LANCZOS)
                    for q in range(86, self.min_quality.get()-1, -6):
                        data = self._encode_to_bytes(small, fmt, q)
                        best = data
                        if len(data) <= target:
                            return data, fmt
        return best, fmt


    def get_preset_data(self):
        return {
            'target_size': self.target_size.get(),
            'target_unit': self.target_unit.get(),
            'min_quality': self.min_quality.get(),
            'max_quality': self.max_quality.get(),
            'output_format': self.output_format.get(),
            'allow_resize': self.allow_resize.get(),
            'retry_strategy': self.retry_strategy.get(),
            'max_width': self.max_width.get(),
            'max_height': self.max_height.get(),
            'include_subdirs': self.include_subdirs.get(),
            'independent_folder': self.independent_folder.get(),
        }

    def apply_preset_data(self, preset):
        self.target_size.set(preset.get('target_size', 0.3))
        self.target_unit.set(preset.get('target_unit', 'MB'))
        self.min_quality.set(preset.get('min_quality', 35))
        self.max_quality.set(preset.get('max_quality', 92))
        self.output_format.set(preset.get('output_format', 'jpg'))
        self.allow_resize.set(preset.get('allow_resize', False))
        self.retry_strategy.set(preset.get('retry_strategy', True))
        self.max_width.set(preset.get('max_width', 2560))
        self.max_height.set(preset.get('max_height', 2560))
        self.include_subdirs.set(preset.get('include_subdirs', True))
        self.independent_folder.set(preset.get('independent_folder', False))
        if self._preview_updater:
            self._preview_updater.trigger()

    def save_preset(self):
        PresetPickerDialog, make_card, make_primary_button, make_secondary_button, save_module_preset(self.preset_module_name, self.get_preset_data())
        messagebox.showinfo('提示', '模板已保存')

    def load_preset(self):
        dlg = PresetPickerDialog(self.parent_frame, self.preset_module_name)
        self.parent_frame.wait_window(dlg)
        preset = dlg.result
        if not preset:
            return
        self.apply_preset_data(preset)

    def process_compress(self):
        if not self.input_path.get():
            messagebox.showerror('错误', '请选择图片文件或文件夹')
            return
        input_path = Path(self.input_path.get())
        if not input_path.exists():
            messagebox.showerror('错误', '输入路径不存在')
            return
        images = list_images(input_path, self.include_subdirs.get())
        if not images:
            messagebox.showwarning('提示', '没有找到图片')
            return

        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        progress = self.create_progress_window('图片压缩中...', len(images))
        progress.output_dir = str(output_base)
        processed, failed = 0, []
        preview_before = None
        preview_after = None

        for i, (img_path, rel_path) in enumerate(images):
            try:
                self.update_progress(progress, i, len(images), str(rel_path))
                img = open_image_with_exif(img_path)
                data, fmt = self.compress_one(img)
                ext = '.jpg' if fmt == 'jpg' else f'.{fmt}'
                base_out = output_base / ('结果集' if self.independent_folder.get() else '')
                out_path = (base_out / rel_path).with_suffix(ext)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(data)
                if preview_before is None:
                    preview_before = str(img_path)
                preview_after = str(out_path)
                processed += 1
            except Exception as e:
                failed.append(f'{rel_path} - {e}')

        extra = f'目标体积: {self.target_size.get()} {self.target_unit.get()}\n失败重试策略: {"开" if self.retry_strategy.get() else "关"}\n独立文件夹: {"是" if self.independent_folder.get() else "否"}'
        if preview_before and preview_after:
            self.preview.show_dual(preview_before, preview_after, prefix_text='原图 / 压缩结果')
        self.finish_processing(progress, processed, failed, '图片压缩', extra)
