
import os
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from PIL import Image
import ttkbootstrap as tb
from ttkbootstrap.constants import *

from common_utils import (
    ImagePreview, bind_drop_to_widget, create_input_row, create_output_row,
    default_output_dir, latest_module_preset, load_module_presets, list_images, open_image_with_exif, remove_exif, save_image_by_format, PresetPickerDialog, make_card, make_primary_button, make_secondary_button, save_module_preset
)


class ExifModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing

        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.include_subdirs = tk.BooleanVar(value=True)
        self.remove_mode = tk.BooleanVar(value=True)
        self.output_format = tk.StringVar(value="original")

        self.input_path.trace_add('write', self.on_input_changed)
        self.preset_module_name = 'exif'
        self.create_ui()
        self.on_input_changed()

    def create_ui(self):
        body = tb.Frame(self.parent_frame)
        body.pack(fill=BOTH, expand=YES)
        left = tb.Frame(body)
        left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 12))
        right = tb.Frame(body)
        right.pack(side=RIGHT, fill=Y)

        box = tb.LabelFrame(left, text='输入输出')
        box.pack(fill=X, pady=(0, 10))
        inner = tb.Frame(box, padding=12); inner.pack(fill=X)
        self.input_entry = create_input_row(inner, '输入路径:', self.input_path)
        create_output_row(inner, '输出目录:', self.output_dir)
        tb.Checkbutton(inner, text='包含子目录', variable=self.include_subdirs, bootstyle='round-toggle', command=self.on_input_changed).pack(anchor=W, pady=(6,0))

        cfg, c = make_card(left, 'EXIF设置', '查看和清理图片元数据')
        tb.Checkbutton(c, text='导出去除EXIF后的图片', variable=self.remove_mode, bootstyle='round-toggle').pack(anchor=W)
        row = tb.Frame(c); row.pack(fill=X, pady=(8,0))
        tb.Label(row, text='输出格式:').pack(side=LEFT, padx=(0, 8))
        for label, value in [('保持原格式', 'original'), ('JPG', 'jpg'), ('PNG', 'png'), ('WEBP', 'webp')]:
            tb.Radiobutton(row, text=label, variable=self.output_format, value=value, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        actions = tb.Frame(left)
        actions.pack(fill=X, pady=8)
        make_secondary_button(actions, '查看首图EXIF', self.show_exif).pack(side=LEFT, padx=(0, 8))
        make_secondary_button(actions, '保存模板', self.save_preset).pack(side=LEFT, padx=(0, 8))
        make_secondary_button(actions, '载入模板', self.load_preset).pack(side=LEFT, padx=(0, 8))
        make_primary_button(actions, '清除EXIF并导出', self.process_remove).pack(side=LEFT)

        self.preview = ImagePreview(right, '图片预览')
        bind_drop_to_widget(self.input_entry, self.handle_drop, accept='any')
        bind_drop_to_widget(self.parent_frame, self.handle_drop, accept='any')

    def get_images(self):
        return list_images(Path(self.input_path.get()), self.include_subdirs.get())

    def on_input_changed(self, *_):
        self.output_dir.set(default_output_dir(self.input_path.get()))
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            self.preview.show(str(p))
        elif p.exists() and p.is_dir():
            self.preview.show_folder_preview(str(p), include_subdirs=self.include_subdirs.get())
        else:
            self.preview.clear()

    def handle_drop(self, path):
        self.input_path.set(path)
        self.on_input_changed()

    def show_exif(self):
        images = self.get_images()
        if not images:
            messagebox.showwarning('提示', '没有可查看的图片')
            return
        img_path = images[0][0]
        img = Image.open(img_path)
        exif = img.getexif()
        if not exif:
            messagebox.showinfo('EXIF信息', '首张图片没有EXIF信息')
            return
        lines = []
        for k, v in exif.items():
            lines.append(f'{k}: {v}')
        messagebox.showinfo('EXIF信息', '\n'.join(lines[:80]))


    def get_preset_data(self):
        return {
            'include_subdirs': self.include_subdirs.get(),
            'remove_mode': self.remove_mode.get(),
            'output_format': self.output_format.get(),
        }

    def apply_preset_data(self, preset):
        self.include_subdirs.set(preset.get('include_subdirs', True))
        self.remove_mode.set(preset.get('remove_mode', True))
        self.output_format.set(preset.get('output_format', 'original'))

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

    def process_remove(self):
        images = self.get_images()
        if not images:
            messagebox.showwarning('提示', '没有找到图片')
            return
        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        progress = self.create_progress_window('EXIF处理中...', len(images))
        progress.output_dir = str(output_base)
        processed, failed = 0, []
        preview_before = None
        preview_after = None
        for i, (img_path, rel_path) in enumerate(images):
            try:
                self.update_progress(progress, i, len(images), str(rel_path))
                img = open_image_with_exif(img_path)
                clean = remove_exif(img)
                saved = save_image_by_format(clean, output_base / rel_path, self.output_format.get())
                if preview_before is None:
                    preview_before = str(img_path)
                preview_after = str(saved)
                processed += 1
            except Exception as e:
                failed.append(f'{rel_path} - {e}')
        if preview_before and preview_after:
            self.preview.show_dual(preview_before, preview_after, prefix_text='原图 / 去EXIF结果')
        self.finish_processing(progress, processed, failed, 'EXIF处理', f'输出格式: {self.output_format.get()}')
