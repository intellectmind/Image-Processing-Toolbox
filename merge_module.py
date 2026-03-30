import os
import tkinter as tk
from tkinter import colorchooser, messagebox
from pathlib import Path
from PIL import Image
import ttkbootstrap as tb
from ttkbootstrap.constants import *

from common_utils import (
    ImagePreview, bind_drop_to_widget, create_input_row, create_output_row,
    default_output_dir, is_image_file, latest_module_preset, load_module_presets, natural_sort_key, open_image_with_exif, save_image_by_format, PresetPickerDialog, make_card, make_primary_button, make_secondary_button, save_module_preset
)


class MergeModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing

        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.output_filename = tk.StringVar(value='merged_result')
        self.direction = tk.StringVar(value='vertical')
        self.spacing = tk.IntVar(value=0)
        self.bg_color = tk.StringVar(value='#FFFFFF')
        self.bg_transparent = tk.BooleanVar(value=False)
        self.sort_order = tk.StringVar(value='asc')
        self.output_format = tk.StringVar(value='png')
        self.independent_folder = tk.BooleanVar(value=False)

        self.input_path.trace_add('write', self.on_input_changed)
        self.preset_module_name = 'merge'
        self.create_ui()
        self.on_input_changed()

    def create_ui(self):
        body = tb.Frame(self.parent_frame)
        body.pack(fill=BOTH, expand=YES)
        left = tb.Frame(body)
        left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 12))
        right = tb.Frame(body)
        right.pack(side=RIGHT, fill=Y)

        dirs, dirs_inner = make_card(left, '输入输出', '选择输入目录和结果保存位置')
        self.input_entry = create_input_row(dirs_inner, '输入路径:', self.input_path)
        create_output_row(dirs_inner, '输出目录:', self.output_dir)
        row_name = tb.Frame(dirs_inner)
        row_name.pack(fill=X, pady=5)
        tb.Label(row_name, text='输出文件:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(row_name, textvariable=self.output_filename).pack(side=LEFT, fill=X, expand=YES, padx=5)
        tb.Checkbutton(dirs, text='输出到独立文件夹', variable=self.independent_folder, bootstyle='round-toggle').pack(anchor=W, pady=(6, 0))

        cfg, cfg_inner = make_card(left, '拼接设置', '统一控制方向、间距、背景和排序')

        row1 = tb.Frame(cfg_inner)
        row1.pack(fill=X, pady=5)
        tb.Label(row1, text='拼接方向:', width=10, anchor=W).pack(side=LEFT)
        tb.Radiobutton(row1, text='垂直拼接', variable=self.direction, value='vertical', bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)
        tb.Radiobutton(row1, text='水平拼接', variable=self.direction, value='horizontal', bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        row2 = tb.Frame(cfg_inner)
        row2.pack(fill=X, pady=5)
        tb.Label(row2, text='排序方式:', width=10, anchor=W).pack(side=LEFT)
        tb.Radiobutton(row2, text='自然升序', variable=self.sort_order, value='asc', bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)
        tb.Radiobutton(row2, text='自然降序', variable=self.sort_order, value='desc', bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        row3 = tb.Frame(cfg_inner)
        row3.pack(fill=X, pady=5)
        tb.Label(row3, text='图片间距:', width=10, anchor=W).pack(side=LEFT)
        tb.Scale(row3, from_=0, to=100, variable=self.spacing, orient=HORIZONTAL, bootstyle='success').pack(side=LEFT, fill=X, expand=YES, padx=(0, 10))
        self.spacing_label = tb.Label(row3, text=f'{self.spacing.get()} px', width=10)
        self.spacing_label.pack(side=LEFT)
        self.spacing.trace_add('write', lambda *_: self.spacing_label.config(text=f'{self.spacing.get()} px'))

        row4 = tb.Frame(cfg_inner)
        row4.pack(fill=X, pady=5)
        tb.Label(row4, text='背景设置:', width=10, anchor=W).pack(side=LEFT)
        tb.Checkbutton(row4, text='透明背景', variable=self.bg_transparent, bootstyle='round-toggle', command=self.toggle_bg_color).pack(side=LEFT, padx=(0, 10))
        tb.Button(row4, text='选择颜色', command=self.choose_color, bootstyle='primary-outline').pack(side=LEFT)
        self.color_preview = tk.Frame(row4, width=36, height=24, bg=self.bg_color.get(), relief='solid', borderwidth=1)
        self.color_preview.pack(side=LEFT, padx=8)
        self.color_preview.pack_propagate(False)

        row5 = tb.Frame(cfg)
        row5.pack(fill=X, pady=5)
        tb.Label(row5, text='输出格式:', width=10, anchor=W).pack(side=LEFT)
        for label, value in [('PNG', 'png'), ('JPG', 'jpg'), ('WEBP', 'webp')]:
            tb.Radiobutton(row5, text=label, variable=self.output_format, value=value, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        action_card, preset_row = make_card(left, '快捷操作', '模板与执行操作统一放在这里')
        preset_row.pack(fill=X, pady=(0, 8))
        make_secondary_button(preset_row, '保存模板', self.save_preset).pack(side=LEFT)
        make_secondary_button(preset_row, '载入模板', self.load_preset).pack(side=LEFT, padx=6)
        make_primary_button(left, '开始拼接', self.process_merge).pack(pady=8)

        self.preview = ImagePreview(right, '图片预览')
        bind_drop_to_widget(self.input_entry, self.handle_drop, accept='any')
        bind_drop_to_widget(self.parent_frame, self.handle_drop, accept='any')

    def on_input_changed(self, *_):
        self.output_dir.set(default_output_dir(self.input_path.get()))
        self.refresh_preview()

    def handle_drop(self, path):
        self.input_path.set(path)
        self.on_input_changed()

    def refresh_preview(self):
        p = Path(self.input_path.get())
        if p.exists() and p.is_file() and is_image_file(p):
            self.preview.show(str(p))
            return
        if p.exists() and p.is_dir():
            imgs = [x for x in p.iterdir() if is_image_file(x)]
            imgs.sort(key=natural_sort_key)
            self.preview.show(str(imgs[0])) if imgs else self.preview.clear()
            return
        self.preview.clear()

    def choose_color(self):
        color = colorchooser.askcolor(initialcolor=self.bg_color.get())[1]
        if color:
            self.bg_color.set(color)
            self.color_preview.configure(bg=color)

    def toggle_bg_color(self):
        self.color_preview.configure(bg='#E9ECEF' if self.bg_transparent.get() else self.bg_color.get())

    def resolve_input_dir(self):
        p = Path(self.input_path.get())
        if p.is_file():
            return p.parent
        return p

    def get_sorted_images(self, input_dir):
        images = [file for file in input_dir.iterdir() if is_image_file(file)]
        images.sort(key=natural_sort_key, reverse=(self.sort_order.get() == 'desc'))
        return images

    def merge_images(self, image_paths):
        images = [open_image_with_exif(img_path) for img_path in image_paths]
        if self.direction.get() == 'vertical':
            total_width = max(img.width for img in images)
            total_height = sum(img.height for img in images) + self.spacing.get() * (len(images) - 1)
        else:
            total_width = sum(img.width for img in images) + self.spacing.get() * (len(images) - 1)
            total_height = max(img.height for img in images)

        if self.bg_transparent.get():
            result = Image.new('RGBA', (total_width, total_height), (255, 255, 255, 0))
        else:
            color = self.bg_color.get()
            bg_color = tuple(int(color[i:i+2], 16) for i in (1, 3, 5)) if color.startswith('#') and len(color) == 7 else (255, 255, 255)
            result = Image.new('RGB', (total_width, total_height), bg_color)

        current_pos = 0
        for img in images:
            if result.mode == 'RGBA' and img.mode != 'RGBA':
                img = img.convert('RGBA')
            elif result.mode == 'RGB' and img.mode == 'RGBA':
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.getchannel('A'))
                img = bg

            if self.direction.get() == 'vertical':
                x_offset = (total_width - img.width) // 2
                result.paste(img, (x_offset, current_pos), img if img.mode == 'RGBA' and result.mode == 'RGBA' else None)
                current_pos += img.height + self.spacing.get()
            else:
                y_offset = (total_height - img.height) // 2
                result.paste(img, (current_pos, y_offset), img if img.mode == 'RGBA' and result.mode == 'RGBA' else None)
                current_pos += img.width + self.spacing.get()
        return result


    def get_preset_data(self):
        return {
            'output_filename': self.output_filename.get(),
            'direction': self.direction.get(),
            'spacing': self.spacing.get(),
            'bg_color': self.bg_color.get(),
            'bg_transparent': self.bg_transparent.get(),
            'sort_order': self.sort_order.get(),
            'output_format': self.output_format.get(),
            'independent_folder': self.independent_folder.get(),
        }

    def apply_preset_data(self, preset):
        self.output_filename.set(preset.get('output_filename', 'merged_result'))
        self.direction.set(preset.get('direction', 'vertical'))
        self.spacing.set(preset.get('spacing', 0))
        self.bg_color.set(preset.get('bg_color', '#FFFFFF'))
        self.bg_transparent.set(preset.get('bg_transparent', False))
        self.sort_order.set(preset.get('sort_order', 'asc'))
        self.output_format.set(preset.get('output_format', 'png'))
        self.independent_folder.set(preset.get('independent_folder', False))
        self.toggle_bg_color()

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

    def process_merge(self):
        if not self.input_path.get():
            messagebox.showerror('错误', '请选择图片文件夹或其中任意一张图片')
            return
        input_dir = self.resolve_input_dir()
        if not input_dir.exists() or not input_dir.is_dir():
            messagebox.showerror('错误', '输入目录不存在')
            return
        if not self.output_filename.get().strip():
            messagebox.showerror('错误', '请输入输出文件名')
            return

        images = self.get_sorted_images(input_dir)
        if len(images) < 2:
            messagebox.showwarning('提示', '至少需要 2 张图片才能拼接')
            return

        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        if self.independent_folder.get():
            output_base = output_base / '拼接结果'

        progress = self.create_progress_window('图片拼接中...', 1)
        progress.output_dir = str(output_base)
        try:
            self.update_progress(progress, 0, 1, f'正在拼接 {len(images)} 张图片')
            result = self.merge_images(images)
            output_path = output_base / self.output_filename.get().strip()
            saved_path = save_image_by_format(result, output_path, self.output_format.get())
            self.preview.show_dual(str(images[0]), str(saved_path), prefix_text='原图（首张） / 拼接结果')
            extra = (
                f'已拼接: {len(images)} 张\n'
                f'拼接方向: {"垂直" if self.direction.get() == "vertical" else "水平"}\n'
                f'排序方式: {"自然升序" if self.sort_order.get() == "asc" else "自然降序"}\n'
                f'独立文件夹: {"是" if self.independent_folder.get() else "否"}'
            )
            self.finish_processing(progress, 1, [], '图片拼接', extra)
        except Exception as e:
            progress.destroy()
            messagebox.showerror('错误', f'拼接失败: {e}')
