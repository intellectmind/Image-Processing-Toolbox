
import os
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import shutil
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from common_utils import (
    ImagePreview, bind_drop_to_widget, create_input_row, image_hash,
    hamming_distance, list_images, make_card, make_primary_button, make_secondary_button,
    open_image_with_exif, open_in_explorer
)

class DedupeModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing
        self.input_path = tk.StringVar(value=os.getcwd())
        self.include_subdirs = tk.BooleanVar(value=True)
        self.threshold = tk.IntVar(value=8)
        self.duplicate_info = []
        self.checkbox_vars = []
        self.create_ui()

    def create_ui(self):
        body = tb.Frame(self.parent_frame); body.pack(fill=BOTH, expand=YES)
        left = tb.Frame(body); left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0,12))
        right = tb.Frame(body); right.pack(side=RIGHT, fill=Y)

        box, inner = make_card(left, '输入与扫描', '选择目录并扫描相似/重复图片')
        self.input_entry = create_input_row(inner, '输入路径:', self.input_path)
        tb.Checkbutton(inner, text='包含子目录', variable=self.include_subdirs, bootstyle='round-toggle').pack(anchor=W, pady=(6,0))

        row = tb.Frame(inner); row.pack(fill=X, pady=6)
        tb.Label(row, text='相似阈值:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(row, textvariable=self.threshold, width=8).pack(side=LEFT)
        tb.Button(row, text='扫描重复图', command=self.process_dedupe, bootstyle='warning').pack(side=LEFT, padx=(10,0))
        tb.Button(row, text='打开目录', command=self.open_folder, bootstyle='secondary-outline').pack(side=LEFT, padx=6)

        action_card, action = make_card(left, '快捷操作', '批量选择与处理重复图片')
        make_secondary_button(action, '全选', self.select_all).pack(side=LEFT)
        make_secondary_button(action, '全不选', self.clear_all).pack(side=LEFT, padx=6)
        tb.Button(action, text='移动选中到 重复图片', command=self.move_selected, bootstyle='info-outline', width=18).pack(side=LEFT, padx=6)
        tb.Button(action, text='删除选中', command=self.delete_selected, bootstyle='danger-outline', width=18).pack(side=LEFT, padx=6)

        table_wrap, table_inner = make_card(left, '扫描结果', '检测到的相似图片会显示在这里')
        table_wrap.pack(fill=BOTH, expand=YES)
        table_inner.pack(fill=BOTH, expand=YES)

        self.canvas = tk.Canvas(table_inner, highlightthickness=0)
        self.scrollbar = tb.Scrollbar(table_inner, orient='vertical', command=self.canvas.yview)
        self.list_frame = tb.Frame(self.canvas)
        self.list_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0,0), window=self.list_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=YES)
        self.scrollbar.pack(side=RIGHT, fill=Y)

        self.preview = ImagePreview(right, '重复图预览')
        bind_drop_to_widget(self.input_entry, self.handle_drop, accept='any')

    def handle_drop(self, path):
        self.input_path.set(path)

    def open_folder(self):
        p = Path(self.input_path.get())
        if p.exists():
            open_in_explorer(p if p.is_dir() else p.parent)

    def render_results(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.checkbox_vars = []
        for idx, (a, b, dist) in enumerate(self.duplicate_info):
            row = tb.Frame(self.list_frame)
            row.pack(fill=X, pady=2)
            var = tk.BooleanVar(value=False)
            self.checkbox_vars.append(var)
            tb.Checkbutton(row, variable=var, bootstyle='round-toggle').pack(side=LEFT)
            tb.Button(row, text='预览', width=6, command=lambda x=idx: self.preview_pair(x), bootstyle='secondary-outline').pack(side=LEFT, padx=(4,6))
            tb.Label(row, text=f'{Path(a).name}  <->  {Path(b).name}  |  距离={dist}', anchor='w').pack(side=LEFT, fill=X, expand=YES)

    def preview_pair(self, idx):
        a, b, dist = self.duplicate_info[idx]
        self.preview.show_dual(a, b, prefix_text=f'相似距离: {dist}')

    def select_all(self):
        for v in self.checkbox_vars:
            v.set(True)

    def clear_all(self):
        for v in self.checkbox_vars:
            v.set(False)

    def selected_pairs(self):
        return [self.duplicate_info[i] for i, v in enumerate(self.checkbox_vars) if v.get()]

    def move_selected(self):
        pairs = self.selected_pairs()
        if not pairs:
            messagebox.showwarning('提示', '请先勾选需要移动的重复图')
            return
        dup_dir = Path(self.input_path.get()) / '重复图片'
        dup_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        for _a, b, _dist in pairs:
            p = Path(b)
            if p.exists():
                target = dup_dir / p.name
                if target.exists():
                    stem = target.stem
                    suffix = target.suffix
                    n = 1
                    while (dup_dir / f'{stem}_{n}{suffix}').exists():
                        n += 1
                    target = dup_dir / f'{stem}_{n}{suffix}'
                shutil.move(str(p), str(target))
                moved += 1
        messagebox.showinfo('完成', f'已移动 {moved} 张重复图到 {dup_dir.name}')

    def delete_selected(self):
        pairs = self.selected_pairs()
        if not pairs:
            messagebox.showwarning('提示', '请先勾选需要删除的重复图')
            return
        if not messagebox.askyesno('确认', '确定删除选中的重复图吗？此操作不可撤销。'):
            return
        deleted = 0
        for _a, b, _dist in pairs:
            p = Path(b)
            if p.exists():
                p.unlink()
                deleted += 1
        messagebox.showinfo('完成', f'已删除 {deleted} 张重复图')

    def process_dedupe(self):
        images = list_images(Path(self.input_path.get()), self.include_subdirs.get())
        if not images:
            messagebox.showwarning('提示','没有找到图片'); return
        progress = self.create_progress_window('重复图扫描中...', len(images))
        hashes = []
        self.duplicate_info = []
        for i, (img_path, rel_path) in enumerate(images):
            try:
                self.update_progress(progress, i, len(images), str(rel_path))
                img = open_image_with_exif(img_path)
                h = image_hash(img)
                for prev_path, prev_hash in hashes:
                    dist = hamming_distance(h, prev_hash)
                    if dist <= self.threshold.get():
                        self.duplicate_info.append((str(prev_path), str(img_path), dist))
                        break
                hashes.append((img_path, h))
            except Exception:
                pass
        progress.destroy()
        self.render_results()
        messagebox.showinfo('扫描完成', f'发现相似/重复图片 {len(self.duplicate_info)} 对')
