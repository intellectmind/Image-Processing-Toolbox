import os
import random
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from PIL import Image
import ttkbootstrap as tb
from ttkbootstrap.constants import *

from common_utils import (
    ImagePreview, bind_drop_to_widget, create_input_row, create_output_row,
    default_output_dir, latest_module_preset, load_module_presets, open_image_with_exif, save_image_by_format, PresetPickerDialog, make_card, make_primary_button, make_secondary_button, save_module_preset
)


class SplitModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing

        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.split_count = tk.IntVar(value=15)
        self.max_height = tk.IntVar(value=2000)
        self.batch_count = tk.IntVar(value=1)
        self.independent_folder = tk.BooleanVar(value=False)
        self.output_format = tk.StringVar(value='original')

        self.input_path.trace_add('write', self.on_input_changed)
        self.preset_module_name = 'split'
        self.create_ui()
        self.on_input_changed()

    def create_ui(self):
        body = tb.Frame(self.parent_frame)
        body.pack(fill=BOTH, expand=YES)
        left = tb.Frame(body)
        left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 12))
        right = tb.Frame(body)
        right.pack(side=RIGHT, fill=Y)

        dirs, dirs_inner = make_card(left, '输入输出', '选择输入图片和结果保存位置')
        self.input_entry = create_input_row(dirs_inner, '输入路径:', self.input_path)
        create_output_row(dirs_inner, '输出目录:', self.output_dir)
        tb.Checkbutton(dirs_inner, text='输出到独立文件夹', variable=self.independent_folder, bootstyle='round-toggle').pack(anchor=W, pady=(6, 0))

        cfg, cfg_inner = make_card(left, '切分设置', '支持随机切分高度和批量方案输出')

        row1 = tb.Frame(cfg_inner)
        row1.pack(fill=X, pady=5)
        tb.Label(row1, text='切分数量:', width=10, anchor=W).pack(side=LEFT)
        tb.Scale(row1, from_=2, to=50, variable=self.split_count, orient=HORIZONTAL, bootstyle='info').pack(side=LEFT, fill=X, expand=YES, padx=(0, 10))
        self.count_label = tb.Label(row1, text=f'{self.split_count.get()} 份', width=10)
        self.count_label.pack(side=LEFT)
        self.split_count.trace_add('write', lambda *_: self.count_label.config(text=f'{self.split_count.get()} 份'))

        row2 = tb.Frame(cfg_inner)
        row2.pack(fill=X, pady=5)
        tb.Label(row2, text='最大高度:', width=10, anchor=W).pack(side=LEFT)
        tb.Scale(row2, from_=500, to=6000, variable=self.max_height, orient=HORIZONTAL, bootstyle='warning').pack(side=LEFT, fill=X, expand=YES, padx=(0, 10))
        self.height_label = tb.Label(row2, text=f'{self.max_height.get()} px', width=10)
        self.height_label.pack(side=LEFT)
        self.max_height.trace_add('write', lambda *_: self.height_label.config(text=f'{self.max_height.get()} px'))

        row3 = tb.Frame(cfg_inner)
        row3.pack(fill=X, pady=5)
        tb.Label(row3, text='批量方案:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(row3, textvariable=self.batch_count, width=10).pack(side=LEFT)
        tb.Label(row3, text='输出格式:').pack(side=LEFT, padx=(20, 10))
        for label, value in [('保持原格式', 'original'), ('JPG', 'jpg'), ('PNG', 'png'), ('WEBP', 'webp')]:
            tb.Radiobutton(row3, text=label, variable=self.output_format, value=value, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        action_card, preset_row = make_card(left, '快捷操作', '模板与执行操作统一放在这里')
        preset_row.pack(fill=X, pady=(0, 8))
        make_secondary_button(preset_row, '保存模板', self.save_preset).pack(side=LEFT)
        make_secondary_button(preset_row, '载入模板', self.load_preset).pack(side=LEFT, padx=6)
        make_primary_button(left, '开始切分', self.process_split).pack(pady=8)

        self.preview = ImagePreview(right, '图片预览')
        bind_drop_to_widget(self.input_entry, self.handle_drop, accept='any')
        bind_drop_to_widget(self.parent_frame, self.handle_drop, accept='any')

    def on_input_changed(self, *_):
        self.output_dir.set(default_output_dir(self.input_path.get()))
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            self.preview.show(str(p))
        elif p.exists() and p.is_dir():
            from common_utils import list_images
            imgs = list_images(p, True)
            self.preview.show(str(imgs[0][0])) if imgs else self.preview.clear()
        else:
            self.preview.clear()

    def handle_drop(self, path):
        self.input_path.set(path)
        self.on_input_changed()

    def split_image_randomly(self, img, num_splits, max_height):
        width, height = img.size
        if height <= max_height or num_splits <= 1:
            return [img.copy()]

        points = [0]
        remaining_height = height
        for i in range(num_splits - 1):
            expected = remaining_height / max(1, (num_splits - i))
            min_h = max(100, int(expected * 0.75))
            max_h = min(max_height, int(expected * 1.25))
            if min_h > max_h:
                min_h = max_h
            current = random.randint(min_h, max_h) if max_h >= min_h else max_h
            next_point = points[-1] + current
            if next_point >= height:
                break
            points.append(next_point)
            remaining_height -= current
        points.append(height)
        points = sorted(set(points))

        parts = []
        for idx in range(len(points) - 1):
            top, bottom = points[idx], points[idx + 1]
            if bottom > top:
                parts.append(img.crop((0, top, width, bottom)))
        return parts


    def get_preset_data(self):
        return {
            'split_count': self.split_count.get(),
            'max_height': self.max_height.get(),
            'batch_count': self.batch_count.get(),
            'independent_folder': self.independent_folder.get(),
            'output_format': self.output_format.get(),
        }

    def apply_preset_data(self, preset):
        self.split_count.set(preset.get('split_count', 15))
        self.max_height.set(preset.get('max_height', 2000))
        self.batch_count.set(preset.get('batch_count', 1))
        self.independent_folder.set(preset.get('independent_folder', False))
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

    def process_split(self):
        if not self.input_path.get():
            messagebox.showerror('错误', '请选择图片文件')
            return
        input_path = Path(self.input_path.get())
        if input_path.is_dir():
            candidates = [p for p in input_path.iterdir() if p.is_file()]
            if not candidates:
                messagebox.showwarning('提示', '文件夹里没有可预览文件')
                return
            input_path = candidates[0]
        if not input_path.exists():
            messagebox.showerror('错误', '输入图片不存在')
            return

        batch_total = max(1, self.batch_count.get())
        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        progress = self.create_progress_window('图片切分中...', batch_total)
        progress.output_dir = str(output_base)
        processed, failed = 0, []
        preview_before = str(input_path)
        preview_after = None

        try:
            img = open_image_with_exif(input_path)
            for batch in range(batch_total):
                self.update_progress(progress, batch, batch_total, f'方案{batch + 1:02d}')
                split_images = self.split_image_randomly(img, self.split_count.get(), self.max_height.get())
                batch_dir = output_base / f'方案{batch + 1:02d}' if self.independent_folder.get() or batch_total > 1 else output_base
                for i, split_img in enumerate(split_images):
                    new_name = f'{input_path.stem}_{i + 1:03d}{input_path.suffix}'
                    saved_path = save_image_by_format(split_img, batch_dir / new_name, self.output_format.get())
                    if preview_after is None:
                        preview_after = str(saved_path)
                    processed += 1
        except Exception as e:
            failed.append(str(e))

        extra = (
            f'切分数量: {self.split_count.get()}\n'
            f'批量方案: {batch_total}\n'
            f'最大高度: {self.max_height.get()} px\n'
            f'独立文件夹: {"是" if self.independent_folder.get() else "否"}'
        )
        if preview_before and preview_after:
            self.preview.show_dual(preview_before, preview_after, prefix_text='原图 / 切分结果（首张）')
        self.finish_processing(progress, processed, failed, '图片切分', extra)
