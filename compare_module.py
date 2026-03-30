
import os
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from PIL import Image, ImageChops
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from common_utils import ImagePreview, bind_drop_to_widget, image_difference_score, make_card, make_primary_button, open_image_with_exif, save_image_by_format

class CompareModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing
        self.file_a = tk.StringVar(value='')
        self.file_b = tk.StringVar(value='')
        self.output_dir = tk.StringVar(value='')
        self.create_ui()

    def create_ui(self):
        body = tb.Frame(self.parent_frame); body.pack(fill=BOTH, expand=YES)
        left = tb.Frame(body); left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0,12))
        right = tb.Frame(body); right.pack(side=RIGHT, fill=Y)
        io_card, io_inner = make_card(left, '输入输出', '选择两张图片并指定差异图输出目录')
        for label, var in [('图片A:', self.file_a), ('图片B:', self.file_b)]:
            row = tb.Frame(io_inner); row.pack(fill=X, pady=5)
            tb.Label(row, text=label, width=10, anchor=W).pack(side=LEFT)
            tb.Entry(row, textvariable=var).pack(side=LEFT, fill=X, expand=YES, padx=6)
            tb.Button(row, text='选择图片', command=lambda v=var: self.pick_file(v), bootstyle='primary-outline', width=12).pack(side=LEFT)
        row = tb.Frame(io_inner); row.pack(fill=X, pady=5)
        tb.Label(row, text='输出目录:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(row, textvariable=self.output_dir).pack(side=LEFT, fill=X, expand=YES, padx=6)
        tb.Button(row, text='浏览', command=self.pick_dir, bootstyle='secondary-outline', width=12).pack(side=LEFT)

        action_card, action_inner = make_card(left, '快捷操作', '生成差异图并查看差异得分')
        make_primary_button(action_inner, '开始对比', self.process_compare).pack(anchor=W, pady=(0, 8))
        self.diff_label = tb.Label(action_inner, text='差异得分：-', font=('微软雅黑', 11, 'bold'))
        self.diff_label.pack(anchor=W)

        self.preview = ImagePreview(right, '图片对比')
        bind_drop_to_widget(left, self.handle_multi_drop, accept='multi')

    def pick_file(self, var):
        from tkinter import filedialog
        f = filedialog.askopenfilename(filetypes=[('图片文件', '*.png *.jpg *.jpeg *.bmp *.gif *.webp')])
        if f:
            var.set(f)
            self.preview.show_dual(self.file_a.get(), self.file_b.get(), prefix_text='原图对比')

    def pick_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d:
            self.output_dir.set(d)

    def handle_multi_drop(self, paths):
        imgs = [p for p in paths if Path(p).suffix.lower() in {'.png','.jpg','.jpeg','.bmp','.gif','.webp'}]
        if len(imgs) >= 1:
            self.file_a.set(imgs[0])
        if len(imgs) >= 2:
            self.file_b.set(imgs[1])
        if self.file_a.get() and self.file_b.get():
            self.preview.show_dual(self.file_a.get(), self.file_b.get(), prefix_text='原图对比')

    def process_compare(self):
        if not self.file_a.get() or not self.file_b.get():
            messagebox.showwarning('提示', '请选择两张图片')
            return
        a = open_image_with_exif(Path(self.file_a.get())).convert('RGB')
        b = open_image_with_exif(Path(self.file_b.get())).convert('RGB')
        w = min(a.width, b.width); h = min(a.height, b.height)
        a = a.resize((w,h)); b = b.resize((w,h))
        diff = ImageChops.difference(a, b)
        score = image_difference_score(a, b)
        self.diff_label.configure(text=f'差异得分：{score:.2f}（越小越相似）')
        outdir = Path(self.output_dir.get() or (Path(self.file_a.get()).parent / '结果'))
        saved = save_image_by_format(diff, outdir / 'difference.png', 'png')
        self.preview.show_dual(self.file_a.get(), str(saved), prefix_text='原图A / 差异图')
