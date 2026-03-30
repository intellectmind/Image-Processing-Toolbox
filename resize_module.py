import os
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from PIL import Image
import ttkbootstrap as tb
from ttkbootstrap.constants import *

from common_utils import (
    ImagePreview, PreviewUpdater, bind_drop_to_widget, create_input_row, create_output_row,
    default_output_dir, latest_module_preset, load_module_presets, list_images, open_image_with_exif, save_image_by_format, PresetPickerDialog, make_card, make_primary_button, make_secondary_button, save_module_preset
)


class ResizeModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing

        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.include_subdirs = tk.BooleanVar(value=True)
        self.independent_folder = tk.BooleanVar(value=False)
        self.width = tk.IntVar(value=1080)
        self.height = tk.IntVar(value=1920)
        self.keep_ratio = tk.BooleanVar(value=True)
        self.resize_mode = tk.StringVar(value='fit')
        self.output_format = tk.StringVar(value='original')

        self.input_path.trace_add('write', self.on_input_changed)
        self._preview_updater = None
        self.preset_module_name = 'resize'
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

        cfg, cfg_inner = make_card(left, '分辨率设置', '统一调整宽高、模式和输出格式')
        r1 = tb.Frame(cfg); r1.pack(fill=X, pady=5)
        tb.Label(r1, text='目标宽度:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(r1, textvariable=self.width, width=10).pack(side=LEFT)
        tb.Label(r1, text='目标高度:', width=10, anchor=W).pack(side=LEFT, padx=(15,0))
        tb.Entry(r1, textvariable=self.height, width=10).pack(side=LEFT)

        r2 = tb.Frame(cfg); r2.pack(fill=X, pady=5)
        tb.Checkbutton(r2, text='保持比例', variable=self.keep_ratio, bootstyle='round-toggle').pack(side=LEFT)
        tb.Label(r2, text='模式:').pack(side=LEFT, padx=(15,8))
        tb.Radiobutton(r2, text='完整适配', variable=self.resize_mode, value='fit', bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)
        tb.Radiobutton(r2, text='强制拉伸', variable=self.resize_mode, value='stretch', bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        r3 = tb.Frame(cfg); r3.pack(fill=X, pady=5)
        tb.Label(r3, text='输出格式:').pack(side=LEFT, padx=(0,10))
        for label, value in [('保持原格式','original'), ('JPG','jpg'), ('PNG','png'), ('WEBP','webp')]:
            tb.Radiobutton(r3, text=label, variable=self.output_format, value=value, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        action_card, preset_row = make_card(left, '快捷操作', '模板与执行操作统一放在这里')
        preset_row.pack(fill=X, pady=(0, 8))
        make_secondary_button(preset_row, '保存模板', self.save_preset).pack(side=LEFT)
        make_secondary_button(preset_row, '载入模板', self.load_preset).pack(side=LEFT, padx=6)
        make_primary_button(left, '开始处理', self.process_resize).pack(pady=8)

        self.preview = ImagePreview(right, '图片预览')
        self._preview_updater = PreviewUpdater(
            self.parent_frame,
            self.preview,
            self._get_preview_source_image,
            self._render_preview_result,
            delay_ms=250
        )
        for var in [self.width, self.height, self.keep_ratio, self.resize_mode]:
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
        if self.resize_mode.get() == 'stretch' or not self.keep_ratio.get():
            return img.resize((self.width.get(), self.height.get()), Image.Resampling.LANCZOS)
        resized = img.copy()
        resized.thumbnail((self.width.get(), self.height.get()), Image.Resampling.LANCZOS)
        return resized

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


    def get_preset_data(self):
        return {
            'width': self.width.get(),
            'height': self.height.get(),
            'keep_ratio': self.keep_ratio.get(),
            'resize_mode': self.resize_mode.get(),
            'output_format': self.output_format.get(),
            'include_subdirs': self.include_subdirs.get(),
            'independent_folder': self.independent_folder.get(),
        }

    def apply_preset_data(self, preset):
        self.width.set(preset.get('width', 1080))
        self.height.set(preset.get('height', 1920))
        self.keep_ratio.set(preset.get('keep_ratio', True))
        self.resize_mode.set(preset.get('resize_mode', 'fit'))
        self.output_format.set(preset.get('output_format', 'original'))
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

    def process_resize(self):
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
        progress = self.create_progress_window('分辨率处理中...', len(images))
        progress.output_dir = str(output_base)
        processed, failed = 0, []
        preview_before = None
        preview_after = None

        for i, (img_path, rel_path) in enumerate(images):
            try:
                self.update_progress(progress, i, len(images), str(rel_path))
                img = open_image_with_exif(img_path)
                if self.resize_mode.get() == 'stretch' or not self.keep_ratio.get():
                    resized = img.resize((self.width.get(), self.height.get()), Image.Resampling.LANCZOS)
                else:
                    resized = img.copy()
                    resized.thumbnail((self.width.get(), self.height.get()), Image.Resampling.LANCZOS)
                base_out = output_base / ('结果集' if self.independent_folder.get() else '')
                out_path = base_out / rel_path
                saved_path = save_image_by_format(resized, out_path, self.output_format.get())
                if preview_before is None:
                    preview_before = str(img_path)
                preview_after = str(saved_path)
                processed += 1
            except Exception as e:
                failed.append(f'{rel_path} - {e}')
        extra = f'目标尺寸: {self.width.get()} x {self.height.get()}\n独立文件夹: {"是" if self.independent_folder.get() else "否"}'
        if preview_before and preview_after:
            self.preview.show_dual(preview_before, preview_after, prefix_text='原图 / 调整结果')
        self.finish_processing(progress, processed, failed, '分辨率更改', extra)
