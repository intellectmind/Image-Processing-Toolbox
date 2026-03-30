
import os
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import shutil
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from common_utils import ImagePreview, bind_drop_to_widget, create_input_row, create_output_row, default_output_dir, latest_module_preset, load_module_presets, list_images, natural_sort_key, PresetPickerDialog, make_card, make_primary_button, make_secondary_button, save_module_preset

class RenameModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing
        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.include_subdirs = tk.BooleanVar(value=True)
        self.prefix = tk.StringVar(value='image')
        self.start_num = tk.IntVar(value=1)
        self.digits = tk.IntVar(value=3)
        self.keep_ext = tk.BooleanVar(value=True)
        self.mode = tk.StringVar(value='copy')
        self.input_path.trace_add('write', self.on_input_changed)
        self.preset_module_name = 'rename'
        self.create_ui(); self.on_input_changed()

    def create_ui(self):
        body = tb.Frame(self.parent_frame); body.pack(fill=BOTH, expand=YES)
        left = tb.Frame(body); left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0,12))
        right = tb.Frame(body); right.pack(side=RIGHT, fill=Y)
        box, inner = make_card(left, '输入输出', '选择输入内容和结果保存位置')
        self.input_entry = create_input_row(inner, '输入路径:', self.input_path)
        create_output_row(inner, '输出目录:', self.output_dir)
        tb.Checkbutton(inner, text='包含子目录', variable=self.include_subdirs, bootstyle='round-toggle', command=self.on_input_changed).pack(anchor=W, pady=(6,0))

        cfg, c = make_card(left, '重命名设置', '控制前缀、编号位数和输出方式')
        r1 = tb.Frame(c); r1.pack(fill=X, pady=4)
        tb.Label(r1, text='前缀:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(r1, textvariable=self.prefix, width=20).pack(side=LEFT)
        tb.Label(r1, text='起始序号:', width=10, anchor=W).pack(side=LEFT, padx=(20,0))
        tb.Entry(r1, textvariable=self.start_num, width=8).pack(side=LEFT)
        r2 = tb.Frame(c); r2.pack(fill=X, pady=4)
        tb.Label(r2, text='位数:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(r2, textvariable=self.digits, width=8).pack(side=LEFT)
        tb.Checkbutton(r2, text='保留扩展名', variable=self.keep_ext, bootstyle='round-toggle').pack(side=LEFT, padx=(20,0))
        tb.Radiobutton(r2, text='复制输出', variable=self.mode, value='copy', bootstyle='toolbutton-outline').pack(side=LEFT, padx=5)
        tb.Radiobutton(r2, text='就地重命名', variable=self.mode, value='rename', bootstyle='toolbutton-outline').pack(side=LEFT, padx=5)

        action_card, preset_row = make_card(left, '快捷操作', '模板与执行操作统一放在这里')
        make_secondary_button(preset_row, '保存模板', self.save_preset).pack(side=LEFT)
        make_secondary_button(preset_row, '载入模板', self.load_preset).pack(side=LEFT, padx=6)
        make_primary_button(left, '开始重命名', self.process_rename).pack(pady=8)
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
            'prefix': self.prefix.get(),
            'start_num': self.start_num.get(),
            'digits': self.digits.get(),
            'keep_ext': self.keep_ext.get(),
            'mode': self.mode.get(),
        }

    def apply_preset_data(self, preset):
        self.include_subdirs.set(preset.get('include_subdirs', True))
        self.prefix.set(preset.get('prefix', 'image'))
        self.start_num.set(preset.get('start_num', 1))
        self.digits.set(preset.get('digits', 3))
        self.keep_ext.set(preset.get('keep_ext', True))
        self.mode.set(preset.get('mode', 'copy'))

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

    def process_rename(self):
        images = list_images(Path(self.input_path.get()), self.include_subdirs.get())
        if not images:
            messagebox.showwarning('提示', '没有找到图片')
            return
        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        progress = self.create_progress_window('重命名中...', len(images))
        progress.output_dir = str(output_base)
        processed, failed = 0, []
        preview_before = None
        preview_after = None
        for i, (img_path, rel_path) in enumerate(images):
            try:
                self.update_progress(progress, i, len(images), str(rel_path))
                num = self.start_num.get() + i
                ext = img_path.suffix if self.keep_ext.get() else ''
                new_name = f"{self.prefix.get()}_{num:0{self.digits.get()}d}{ext}"
                if self.mode.get() == 'rename':
                    target = img_path.with_name(new_name)
                    img_path.rename(target)
                else:
                    target = (output_base / rel_path).with_name(new_name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(img_path, target)
                if preview_before is None:
                    preview_before = str(img_path)
                preview_after = str(target)
                processed += 1
            except Exception as e:
                failed.append(f'{rel_path} - {e}')
        if preview_before and preview_after:
            self.preview.show_dual(preview_before, preview_after, prefix_text='原图 / 重命名结果')
        self.finish_processing(progress, processed, failed, '图片重命名', f'前缀: {self.prefix.get()}')
