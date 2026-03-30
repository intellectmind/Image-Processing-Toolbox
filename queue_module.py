
import json
import os
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from PIL import Image
import shutil
import ttkbootstrap as tb
from ttkbootstrap.constants import *

from common_utils import DATA_DIR, default_output_dir, list_images, make_card, make_primary_button, make_secondary_button, open_image_with_exif, remove_exif, save_image_by_format, open_in_explorer, bind_drop_to_widget

QUEUE_FILE = DATA_DIR / "workflow_templates.json"

class QueueModule:
    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing
        self.tasks = []

        self.task_name = tk.StringVar(value='任务1')
        self.task_type = tk.StringVar(value='格式转换')
        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar(value='')
        self.param1 = tk.StringVar(value='jpg')
        self.param2 = tk.StringVar(value='')

        self.create_ui()
        self.load_templates()

    def create_ui(self):
        top = tb.Frame(self.parent_frame)
        top.pack(fill=BOTH, expand=YES)

        left = tb.Frame(top)
        left.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 12))
        right = tb.Frame(top)
        right.pack(side=RIGHT, fill=Y)

        cfg, c = make_card(left, '任务编辑', '创建、编辑并调整队列中的任务')
        r1 = tb.Frame(c); r1.pack(fill=X, pady=4)
        tb.Label(r1, text='任务名:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(r1, textvariable=self.task_name).pack(side=LEFT, fill=X, expand=YES, padx=6)
        tb.Label(r1, text='任务类型:').pack(side=LEFT, padx=(10,6))
        tb.Combobox(r1, textvariable=self.task_type, values=['格式转换','重命名','分辨率','压缩','EXIF清除','旋转'], width=12, state='readonly').pack(side=LEFT)

        r2 = tb.Frame(c); r2.pack(fill=X, pady=4)
        tb.Label(r2, text='输入路径:', width=10, anchor=W).pack(side=LEFT)
        self._input_entry = tb.Entry(r2, textvariable=self.input_path)
        self._input_entry.pack(side=LEFT, fill=X, expand=YES, padx=6)
        tb.Button(r2, text='文件夹', command=self.pick_dir, bootstyle='secondary-outline').pack(side=LEFT)
        tb.Button(r2, text='打开', command=self.open_input, bootstyle='secondary-outline').pack(side=LEFT, padx=6)
        bind_drop_to_widget(self._input_entry, lambda p: self.input_path.set(p), accept='any')

        r3 = tb.Frame(c); r3.pack(fill=X, pady=4)
        tb.Label(r3, text='输出目录:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(r3, textvariable=self.output_dir).pack(side=LEFT, fill=X, expand=YES, padx=6)
        tb.Button(r3, text='浏览', command=self.pick_out, bootstyle='secondary-outline').pack(side=LEFT)

        r4 = tb.Frame(c); r4.pack(fill=X, pady=4)
        tb.Label(r4, text='参数1:', width=10, anchor=W).pack(side=LEFT)
        tb.Entry(r4, textvariable=self.param1).pack(side=LEFT, fill=X, expand=YES, padx=6)
        tb.Label(r4, text='参数2:', width=10, anchor=W).pack(side=LEFT, padx=(10,0))
        tb.Entry(r4, textvariable=self.param2).pack(side=LEFT, fill=X, expand=YES, padx=6)

        btns = tb.Frame(c); btns.pack(fill=X, pady=(8,0))
        make_primary_button(btns, '添加到队列', self.add_task).pack(side=LEFT)
        tb.Button(btns, text='更新选中', command=self.update_task, bootstyle='warning-outline', width=18).pack(side=LEFT, padx=6)
        tb.Button(btns, text='保存为模板', command=self.save_template, bootstyle='info-outline', width=18).pack(side=LEFT, padx=6)
        tb.Button(btns, text='执行全部', command=self.run_queue, bootstyle='success', width=18).pack(side=LEFT, padx=6)

        list_wrap, lw = make_card(left, '任务队列', '队列中的任务会按顺序依次执行')
        list_wrap.pack(fill=BOTH, expand=YES)
        lw.pack(fill=BOTH, expand=YES)
        self.listbox = tk.Listbox(lw, height=18)
        self.listbox.pack(fill=BOTH, expand=YES)
        self.listbox.bind('<<ListboxSelect>>', self.on_select_task)
        bottom = tb.Frame(lw); bottom.pack(fill=X, pady=(8,0))
        make_secondary_button(bottom, '上移', self.move_up).pack(side=LEFT)
        make_secondary_button(bottom, '下移', self.move_down).pack(side=LEFT, padx=6)
        tb.Button(bottom, text='删除选中', command=self.remove_selected, bootstyle='danger-outline', width=18).pack(side=LEFT, padx=6)
        make_secondary_button(bottom, '清空队列', self.clear_tasks).pack(side=LEFT, padx=6)

        tmpl, t = make_card(right, '流程模板', '保存和载入常用任务流程模板')
        tmpl.pack(fill=BOTH, expand=YES)
        t.pack(fill=BOTH, expand=YES)
        self.template_list = tk.Listbox(t, width=26, height=18)
        self.template_list.pack(fill=BOTH, expand=YES)
        tb.Button(t, text='载入模板', command=self.load_selected_template, bootstyle='primary-outline', width=18).pack(fill=X, pady=(8,0))
        tb.Button(t, text='删除模板', command=self.delete_selected_template, bootstyle='danger-outline', width=18).pack(fill=X, pady=(6,0))

    def pick_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d: self.input_path.set(d)

    def pick_out(self):
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d: self.output_dir.set(d)

    def open_input(self):
        p = Path(self.input_path.get())
        if p.exists():
            open_in_explorer(p)

    def current_form_task(self):
        return {
            'name': self.task_name.get().strip() or f'任务{len(self.tasks)+1}',
            'type': self.task_type.get(),
            'input': self.input_path.get().strip(),
            'output': self.output_dir.get().strip() or default_output_dir(self.input_path.get()),
            'param1': self.param1.get().strip(),
            'param2': self.param2.get().strip(),
        }

    def add_task(self):
        self.tasks.append(self.current_form_task())
        self.refresh_list()

    def update_task(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('提示', '请先在队列中选择一个任务')
            return
        self.tasks[sel[0]] = self.current_form_task()
        self.refresh_list()
        self.listbox.selection_set(sel[0])

    def refresh_list(self):
        self.listbox.delete(0, 'end')
        for idx, t in enumerate(self.tasks, 1):
            self.listbox.insert('end', f"{idx:02d}. {t['name']} | {t['type']} | {Path(t['input']).name if t['input'] else '-'}")

    def on_select_task(self, _event=None):
        sel = self.listbox.curselection()
        if not sel: return
        t = self.tasks[sel[0]]
        self.task_name.set(t['name'])
        self.task_type.set(t['type'])
        self.input_path.set(t['input'])
        self.output_dir.set(t['output'])
        self.param1.set(t.get('param1',''))
        self.param2.set(t.get('param2',''))

    def move_up(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] == 0: return
        i = sel[0]
        self.tasks[i-1], self.tasks[i] = self.tasks[i], self.tasks[i-1]
        self.refresh_list()
        self.listbox.selection_set(i-1)

    def move_down(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self.tasks)-1: return
        i = sel[0]
        self.tasks[i+1], self.tasks[i] = self.tasks[i], self.tasks[i+1]
        self.refresh_list()
        self.listbox.selection_set(i+1)

    def remove_selected(self):
        sel = self.listbox.curselection()
        if not sel: return
        del self.tasks[sel[0]]
        self.refresh_list()

    def clear_tasks(self):
        self.tasks.clear()
        self.refresh_list()

    def load_templates(self):
        self.templates = []
        if QUEUE_FILE.exists():
            try:
                self.templates = json.loads(QUEUE_FILE.read_text(encoding='utf-8'))
            except Exception:
                self.templates = []
        self.template_list.delete(0, 'end')
        for item in self.templates:
            self.template_list.insert('end', item.get('template_name','未命名模板'))

    def save_template(self):
        name = self.task_name.get().strip() or f'模板{len(self.templates)+1}'
        template = {'template_name': name, 'tasks': self.tasks[:] + [self.current_form_task()]}
        self.templates.append(template)
        QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_FILE.write_text(json.dumps(self.templates, ensure_ascii=False, indent=2), encoding='utf-8')
        self.load_templates()
        messagebox.showinfo('提示', '模板已保存')

    def load_selected_template(self):
        sel = self.template_list.curselection()
        if not sel: return
        self.tasks = self.templates[sel[0]].get('tasks', [])
        self.refresh_list()

    def delete_selected_template(self):
        sel = self.template_list.curselection()
        if not sel: return
        del self.templates[sel[0]]
        QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_FILE.write_text(json.dumps(self.templates, ensure_ascii=False, indent=2), encoding='utf-8')
        self.load_templates()

    def _run_task(self, task):
        input_path = Path(task['input'])
        output_base = Path(task['output'])
        task_type = task['type']
        images = list_images(input_path, True)
        count = 0
        for img_path, rel_path in images:
            img = open_image_with_exif(img_path)
            if task_type == '格式转换':
                save_image_by_format(img, output_base / rel_path, task['param1'] or 'jpg')
            elif task_type == '重命名':
                ext = img_path.suffix
                idx = count + 1
                new_name = f"{task['param1'] or 'image'}_{idx:03d}{ext}"
                target = (output_base / rel_path).with_name(new_name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(img_path, target)
            elif task_type == '分辨率':
                width = int(task['param1'] or 1080); height = int(task['param2'] or 1080)
                resized = img.copy(); resized.thumbnail((width, height), Image.Resampling.LANCZOS)
                save_image_by_format(resized, output_base / rel_path, 'original')
            elif task_type == '压缩':
                save_image_by_format(img, output_base / rel_path, 'jpg', jpg_quality=max(20, min(95, int(task['param1'] or 75))))
            elif task_type == 'EXIF清除':
                clean = remove_exif(img)
                save_image_by_format(clean, output_base / rel_path, 'original')
            elif task_type == '旋转':
                rotated = img.rotate(-int(task['param1'] or 90), expand=True)
                save_image_by_format(rotated, output_base / rel_path, 'original')
            count += 1
        return count

    def run_queue(self):
        if not self.tasks:
            messagebox.showwarning('提示','队列为空'); return
        progress = self.create_progress_window('任务队列执行中...', len(self.tasks))
        processed, failed = 0, []
        for i, task in enumerate(self.tasks):
            try:
                self.update_progress(progress, i, len(self.tasks), task['name'])
                processed += self._run_task(task)
            except Exception as e:
                failed.append(f"{task['name']} - {e}")
        self.finish_processing(progress, processed, failed, '任务队列', f'任务数: {len(self.tasks)}')
