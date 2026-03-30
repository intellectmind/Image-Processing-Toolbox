
import os
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from common_utils import (
    ImagePreview, bind_drop_to_widget, create_input_row, create_output_row,
    default_output_dir, latest_module_preset, load_module_presets, list_images, open_image_with_exif, save_image_by_format, PresetPickerDialog, make_card, make_primary_button, make_secondary_button, save_module_preset
)

class ConvertModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing
        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.include_subdirs = tk.BooleanVar(value=True)
        self.output_format = tk.StringVar(value='jpg')
        self.keep_original = tk.BooleanVar(value=False)

        self.input_path.trace_add('write', self.on_input_changed)
        self.preset_module_name = 'convert'
        self.create_ui(); self.on_input_changed()

    def create_ui(self):
        body = tb.Frame(self.parent_frame); body.pack(fill=BOTH, expand=YES)
        left = tb.Frame(body); left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0,12))
        right = tb.Frame(body); right.pack(side=RIGHT, fill=Y)

        box, inner = make_card(left, '输入输出', '选择输入内容和结果保存位置')
        self.input_entry = create_input_row(inner, '输入路径:', self.input_path)
        create_output_row(inner, '输出目录:', self.output_dir)
        tb.Checkbutton(inner, text='包含子目录', variable=self.include_subdirs, bootstyle='round-toggle', command=self.on_input_changed).pack(anchor=W, pady=(6,0))
        tb.Checkbutton(inner, text='保留原文件扩展名副本', variable=self.keep_original, bootstyle='round-toggle').pack(anchor=W)

        cfg, c = make_card(left, '转换设置', '统一转换输出格式与副本策略')
        tb.Label(c, text='目标格式:').pack(side=LEFT, padx=(0,8))
        for label, value in [('JPG','jpg'), ('PNG','png'), ('WEBP','webp')]:
            tb.Radiobutton(c, text=label, variable=self.output_format, value=value, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        action_card, preset_row = make_card(left, '快捷操作', '模板与执行操作统一放在这里')
        make_secondary_button(preset_row, '保存模板', self.save_preset).pack(side=LEFT)
        make_secondary_button(preset_row, '载入模板', self.load_preset).pack(side=LEFT, padx=6)
        make_primary_button(left, '开始转换', self.process_convert).pack(pady=8)
        self.preview = ImagePreview(right, '图片预览')
        bind_drop_to_widget(self.input_entry, self.handle_drop, accept='any')
        bind_drop_to_widget(self.parent_frame, self.handle_drop, accept='any')

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


    def get_preset_data(self):
        return {
            'include_subdirs': self.include_subdirs.get(),
            'output_format': self.output_format.get(),
            'keep_original': self.keep_original.get(),
        }

    def apply_preset_data(self, preset):
        self.include_subdirs.set(preset.get('include_subdirs', True))
        self.output_format.set(preset.get('output_format', 'jpg'))
        self.keep_original.set(preset.get('keep_original', False))

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

    def process_convert(self):
        images = list_images(Path(self.input_path.get()), self.include_subdirs.get())
        if not images:
            messagebox.showwarning('提示', '没有找到图片')
            return
        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        progress = self.create_progress_window('格式转换中...', len(images))
        progress.output_dir = str(output_base)
        processed, failed = 0, []
        preview_before = None
        preview_after = None
        for i, (img_path, rel_path) in enumerate(images):
            try:
                self.update_progress(progress, i, len(images), str(rel_path))
                img = open_image_with_exif(img_path)
                saved = save_image_by_format(img, output_base / rel_path, self.output_format.get())
                if preview_before is None:
                    preview_before = str(img_path)
                preview_after = str(saved)
                if self.keep_original.get():
                    save_image_by_format(img, output_base / rel_path, 'original')
                processed += 1
            except Exception as e:
                failed.append(f'{rel_path} - {e}')
        if preview_before and preview_after:
            self.preview.show_dual(preview_before, preview_after, prefix_text='原图 / 转换结果')
        self.finish_processing(progress, processed, failed, '格式转换', f'目标格式: {self.output_format.get().upper()}')
