
import os
import tkinter as tk
from tkinter import colorchooser, messagebox
from pathlib import Path
from PIL import Image
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from common_utils import (
    ImagePreview, PreviewUpdater, add_background, add_border, bind_drop_to_widget,
    create_input_row, create_output_row, default_output_dir, latest_module_preset, load_module_presets, list_images,
    open_image_with_exif, save_image_by_format, PresetPickerDialog, make_card, make_primary_button, make_secondary_button, save_module_preset
)

class TransformModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing
        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.include_subdirs = tk.BooleanVar(value=True)
        self.rotate = tk.IntVar(value=0)
        self.flip_h = tk.BooleanVar(value=False)
        self.flip_v = tk.BooleanVar(value=False)
        self.border_px = tk.IntVar(value=0)
        self.border_color = '#FFFFFF'
        self.bg_enable = tk.BooleanVar(value=False)
        self.bg_color = '#FFFFFF'
        self.output_format = tk.StringVar(value='original')
        self._preview_updater = None
        self.preset_module_name = 'transform'

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

        cfg, c = make_card(left, '变换设置', '统一控制旋转、翻转、边框与背景')
        r1 = tb.Frame(c); r1.pack(fill=X, pady=4)
        tb.Label(r1, text='旋转角度:', width=10, anchor=W).pack(side=LEFT)
        tb.Combobox(r1, textvariable=self.rotate, values=[0,90,180,270], width=10, state='readonly').pack(side=LEFT)
        tb.Checkbutton(r1, text='水平翻转', variable=self.flip_h, bootstyle='round-toggle').pack(side=LEFT, padx=(20,0))
        tb.Checkbutton(r1, text='垂直翻转', variable=self.flip_v, bootstyle='round-toggle').pack(side=LEFT, padx=(10,0))

        r2 = tb.Frame(c); r2.pack(fill=X, pady=4)
        tb.Label(r2, text='边框像素:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(r2, textvariable=self.border_px, width=10).pack(side=LEFT)
        tb.Button(r2, text='边框颜色', command=self.pick_border, bootstyle='secondary-outline').pack(side=LEFT, padx=8)

        r3 = tb.Frame(c); r3.pack(fill=X, pady=4)
        tb.Checkbutton(r3, text='加背景色', variable=self.bg_enable, bootstyle='round-toggle').pack(side=LEFT)
        tb.Button(r3, text='背景颜色', command=self.pick_bg, bootstyle='secondary-outline').pack(side=LEFT, padx=8)
        tb.Label(r3, text='输出格式:').pack(side=LEFT, padx=(20, 8))
        for label, value in [('保持原格式','original'),('JPG','jpg'),('PNG','png'),('WEBP','webp')]:
            tb.Radiobutton(r3, text=label, variable=self.output_format, value=value, bootstyle='toolbutton-outline').pack(side=LEFT, padx=3)

        action_card, preset_row = make_card(left, '快捷操作', '模板与执行操作统一放在这里')
        make_secondary_button(preset_row, '保存模板', self.save_preset).pack(side=LEFT)
        make_secondary_button(preset_row, '载入模板', self.load_preset).pack(side=LEFT, padx=6)
        make_primary_button(left, '开始处理', self.process_transform).pack(pady=8)
        self.preview = ImagePreview(right, '图片预览')
        self._preview_updater = PreviewUpdater(self.parent_frame, self.preview, self._get_preview_source_image, self._render_preview_result, 250)
        for var in [self.rotate, self.flip_h, self.flip_v, self.border_px, self.bg_enable]:
            try: var.trace_add('write', self._preview_updater.trigger)
            except Exception: pass
        bind_drop_to_widget(self.input_entry, self.handle_drop, accept='any')
        bind_drop_to_widget(self.parent_frame, self.handle_drop, accept='any')

    def pick_border(self):
        c = colorchooser.askcolor(initialcolor=self.border_color)[1]
        if c:
            self.border_color = c
            self._preview_updater.trigger()

    def pick_bg(self):
        c = colorchooser.askcolor(initialcolor=self.bg_color)[1]
        if c:
            self.bg_color = c
            self._preview_updater.trigger()

    def _get_preview_source_image(self):
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            return open_image_with_exif(p)
        if p.exists() and p.is_dir():
            imgs = list_images(p, self.include_subdirs.get())
            if imgs: return open_image_with_exif(imgs[0][0])
        return None

    def apply_transform(self, img):
        if self.rotate.get():
            img = img.rotate(-int(self.rotate.get()), expand=True)
        if self.flip_h.get():
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if self.flip_v.get():
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        if self.border_px.get() > 0:
            img = add_border(img, self.border_px.get(), self.border_color)
        if self.bg_enable.get():
            img = add_background(img, self.bg_color)
        return img

    def _render_preview_result(self, img):
        return self.apply_transform(img)

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
            'rotate': self.rotate.get(),
            'flip_h': self.flip_h.get(),
            'flip_v': self.flip_v.get(),
            'border_px': self.border_px.get(),
            'border_color': self.border_color,
            'bg_enable': self.bg_enable.get(),
            'bg_color': self.bg_color,
            'output_format': self.output_format.get(),
            'include_subdirs': self.include_subdirs.get(),
        }

    def apply_preset_data(self, preset):
        self.rotate.set(preset.get('rotate', 0))
        self.flip_h.set(preset.get('flip_h', False))
        self.flip_v.set(preset.get('flip_v', False))
        self.border_px.set(preset.get('border_px', 0))
        self.border_color = preset.get('border_color', '#FFFFFF')
        self.bg_enable.set(preset.get('bg_enable', False))
        self.bg_color = preset.get('bg_color', '#FFFFFF')
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

    def process_transform(self):
        images = list_images(Path(self.input_path.get()), self.include_subdirs.get())
        if not images:
            messagebox.showwarning('提示','没有找到图片'); return
        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        progress = self.create_progress_window('图片变换中...', len(images))
        progress.output_dir = str(output_base)
        processed, failed = 0, []
        preview_before = preview_after = None
        for i,(img_path, rel_path) in enumerate(images):
            try:
                self.update_progress(progress, i, len(images), str(rel_path))
                img = open_image_with_exif(img_path)
                result = self.apply_transform(img)
                saved = save_image_by_format(result, output_base / rel_path, self.output_format.get())
                if preview_before is None: preview_before = str(img_path)
                preview_after = str(saved)
                processed += 1
            except Exception as e:
                failed.append(f'{rel_path} - {e}')
        if preview_before and preview_after:
            self.preview.show_dual(preview_before, preview_after, prefix_text='原图 / 变换结果')
        self.finish_processing(progress, processed, failed, '旋转/边框/背景', f'旋转: {self.rotate.get()}°')
