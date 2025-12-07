import os
import subprocess
import tkinter as tk
from tkinter import messagebox
import pyperclip

# 配置 Notepad++ 的路径（请根据你的安装位置修改）
NOTEPADPP_PATH = r"C:\Program Files\Notepad++\notepad++.exe"

def is_python_file(path: str) -> bool:
    """判断是否为 .py 文件路径"""
    return path.strip().lower().endswith(".py") and os.path.isfile(path.strip())

def open_with_notepadpp(path: str):
    """调用 Notepad++ 打开文件"""
    try:
        subprocess.Popen([NOTEPADPP_PATH, path])
    except Exception as e:
        messagebox.showerror("错误", f"无法打开文件:\n{e}")

def check_clipboard():
    """定时检查剪贴板内容"""
    text = pyperclip.paste().strip()
    if is_python_file(text):
        status_label.config(text=f"检测到路径: {text}")
        open_button.config(state=tk.NORMAL, command=lambda: open_with_notepadpp(text))
    else:
        status_label.config(text="剪贴板内容不是有效的 .py 文件路径")
        open_button.config(state=tk.DISABLED)
    root.after(1000, check_clipboard)  # 每隔 1 秒检查一次

# 创建主窗口
root = tk.Tk()
root.title("Python 文件路径检测器")
root.geometry("500x200")

status_label = tk.Label(root, text="请在网页上滑选并复制路径")
status_label.pack(pady=20)

open_button = tk.Button(root, text="打开文件", state=tk.DISABLED)
open_button.pack(pady=20)

# 启动定时器
check_clipboard()

root.mainloop()
