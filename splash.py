
import tkinter as tk
import ttkbootstrap as tb

def show_splash(root, duration=1200):
    splash = tb.Toplevel(root)
    splash.overrideredirect(True)
    splash.geometry("420x200")

    frame = tb.Frame(splash, padding=20)
    frame.pack(fill="both", expand=True)

    tb.Label(frame, text="图片处理工具", font=("微软雅黑", 20, "bold")).pack(pady=10)
    tb.Label(frame, text="v1.0 Pro", bootstyle="secondary").pack()
    tb.Label(frame, text="Author: Kurt", bootstyle="info").pack(pady=6)
    tb.Label(frame, text="Loading modules...", bootstyle="secondary").pack(pady=10)

    splash.update_idletasks()
    x = (splash.winfo_screenwidth()//2) - 210
    y = (splash.winfo_screenheight()//2) - 100
    splash.geometry(f"+{x}+{y}")

    root.after(duration, splash.destroy)
