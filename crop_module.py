
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

class CropModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing
        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.include_subdirs = tk.BooleanVar(value=True)
        self.crop_mode = tk.StringVar(value='ratio')
        self.ratio = tk.StringVar(value='1:1')
        self.left_px = tk.IntVar(value=0)
        self.top_px = tk.IntVar(value=0)
        self.right_px = tk.IntVar(value=0)
        self.bottom_px = tk.IntVar(value=0)
        self.output_format = tk.StringVar(value='original')
        self._preview_updater = None
        self.preset_module_name = 'crop'

        self.input_path.trace_add('write', self.on_input_changed)
        self.create_ui(); self.on_input_changed()

    def create_ui(self):
        body = tb.Frame(self.parent_frame); body.pack(fill=BOTH, expand=YES)
        left = tb.Frame(body); left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0,12))
        right = tb.Frame(body); right.pack(side=RIGHT, fill=Y)
        box, inner = make_card(left, '输入输出', '选择输入内容和结果保存位置')
        self.input_entry = create_input_row(inner, '输入路径:', self.input_path)
        create_output_row(inner, '输出目录:', self.output_dir)
        tb.Checkbutton(inner, text='包含子目录', variable=self.include_subdirs, bootstyle='round-toggle', command=self.on_input_changed).pack(anchor=W, pady=(6,0))

        cfg, c = make_card(left, '裁剪设置', '支持比例裁剪与像素裁剪')
        r1 = tb.Frame(c); r1.pack(fill=X, pady=4)
        tb.Radiobutton(r1, text='比例裁剪', variable=self.crop_mode, value='ratio', bootstyle='toolbutton-outline').pack(side=LEFT, padx=4)
        tb.Radiobutton(r1, text='像素裁剪', variable=self.crop_mode, value='pixel', bootstyle='toolbutton-outline').pack(side=LEFT, padx=4)
        tb.Label(r1, text='比例:').pack(side=LEFT, padx=(20,6))
        tb.Combobox(r1, textvariable=self.ratio, values=['1:1','4:3','16:9','3:4','9:16'], width=10, state='readonly').pack(side=LEFT)

        r2 = tb.Frame(c); r2.pack(fill=X, pady=4)
        for lab, var in [('左',self.left_px),('上',self.top_px),('右',self.right_px),('下',self.bottom_px)]:
            tb.Label(r2, text=f'{lab}:').pack(side=LEFT, padx=(0,4))
            tb.Entry(r2, textvariable=var, width=6).pack(side=LEFT, padx=(0,8))

        r3 = tb.Frame(c); r3.pack(fill=X, pady=4)
        tb.Label(r3, text='输出格式:').pack(side=LEFT, padx=(0,8))
        for label, value in [('保持原格式','original'),('JPG','jpg'),('PNG','png'),('WEBP','webp')]:
            tb.Radiobutton(r3, text=label, variable=self.output_format, value=value, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        action_card, preset_row = make_card(left, '快捷操作', '模板与执行操作统一放在这里')
        preset_row.pack(fill=X, pady=(0, 8))
        make_secondary_button(preset_row, '保存模板', self.save_preset).pack(side=LEFT)
        make_secondary_button(preset_row, '载入模板', self.load_preset).pack(side=LEFT, padx=6)
        make_primary_button(left, '开始裁剪', self.process_crop).pack(pady=8)
        self.preview = ImagePreview(right, '图片预览')
        self._preview_updater = PreviewUpdater(self.parent_frame, self.preview, self._get_preview_source_image, self._render_preview_result, delay_ms=250)
        for var in [self.crop_mode, self.ratio, self.left_px, self.top_px, self.right_px, self.bottom_px]:
            try: var.trace_add('write', self._preview_updater.trigger)
            except Exception: pass
        bind_drop_to_widget(self.input_entry, self.handle_drop, accept='any')
        bind_drop_to_widget(self.parent_frame, self.handle_drop, accept='any')

    def _get_preview_source_image(self):
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            return open_image_with_exif(p)
        if p.exists() and p.is_dir():
            imgs = list_images(p, self.include_subdirs.get())
            if imgs: return open_image_with_exif(imgs[0][0])
        return None

    def _render_preview_result(self, img):
        return self.crop_image(img)

    def crop_image(self, img):
        if self.crop_mode.get() == 'ratio':
            ratio_w, ratio_h = map(int, self.ratio.get().split(':'))
            w, h = img.size
            target_ratio = ratio_w / ratio_h
            current_ratio = w / h
            if current_ratio > target_ratio:
                new_w = int(h * target_ratio)
                left = (w - new_w) // 2
                return img.crop((left, 0, left + new_w, h))
            else:
                new_h = int(w / target_ratio)
                top = (h - new_h) // 2
                return img.crop((0, top, w, top + new_h))
        w, h = img.size
        l = max(0, self.left_px.get()); t = max(0, self.top_px.get())
        r = min(w, w - max(0, self.right_px.get())); b = min(h, h - max(0, self.bottom_px.get()))
        if r <= l or b <= t:
            return img
        return img.crop((l, t, r, b))

    def on_input_changed(self, *_):
        self.output_dir.set(default_output_dir(self.input_path.get()))
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            self.preview.show(str(p))
        elif p.exists() and p.is_dir():
            self.preview.show_folder_preview(str(p), include_subdirs=self.include_subdirs.get())
        else:
            self.preview.clear()
        if self._preview_updater: self._preview_updater.trigger()

    def handle_drop(self, path):
        self.input_path.set(path)


    def get_preset_data(self):
        return {
            'crop_mode': self.crop_mode.get(),
            'ratio': self.ratio.get(),
            'left_px': self.left_px.get(),
            'top_px': self.top_px.get(),
            'right_px': self.right_px.get(),
            'bottom_px': self.bottom_px.get(),
            'output_format': self.output_format.get(),
            'include_subdirs': self.include_subdirs.get(),
        }

    def apply_preset_data(self, preset):
        self.crop_mode.set(preset.get('crop_mode', 'ratio'))
        self.ratio.set(preset.get('ratio', '1:1'))
        self.left_px.set(preset.get('left_px', 0))
        self.top_px.set(preset.get('top_px', 0))
        self.right_px.set(preset.get('right_px', 0))
        self.bottom_px.set(preset.get('bottom_px', 0))
        self.output_format.set(preset.get('output_format', 'original'))
        self.include_subdirs.set(preset.get('include_subdirs', True))
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

    def process_crop(self):
        images = list_images(Path(self.input_path.get()), self.include_subdirs.get())
        if not images:
            messagebox.showwarning('提示','没有找到图片'); return
        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        progress = self.create_progress_window('图片裁剪中...', len(images))
        progress.output_dir = str(output_base)
        processed, failed = 0, []
        preview_before = preview_after = None
        for i,(img_path, rel_path) in enumerate(images):
            try:
                self.update_progress(progress,i,len(images),str(rel_path))
                img = open_image_with_exif(img_path)
                cropped = self.crop_image(img)
                saved = save_image_by_format(cropped, output_base / rel_path, self.output_format.get())
                if preview_before is None: preview_before = str(img_path)
                preview_after = str(saved)
                processed += 1
            except Exception as e:
                failed.append(f'{rel_path} - {e}')
        if preview_before and preview_after:
            self.preview.show_dual(preview_before, preview_after, prefix_text='原图 / 裁剪结果')
        self.finish_processing(progress, processed, failed, '图片裁剪', f'裁剪模式: {self.crop_mode.get()}')
