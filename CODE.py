# 运行前, 请确保已安装必要的第三方库:
# pip install google-generativeai pygments darkdetect

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import google.generativeai as genai
import json
import os
import sys
import subprocess
import threading
from pathlib import Path
from io import StringIO
from pygments import lex
from pygments.lexers import get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.token import Token
import darkdetect
import re

# 自定义代码编辑器控件
class LineNumbers(tk.Canvas):
    def __init__(self, *args, **kwargs):
        tk.Canvas.__init__(self, *args, **kwargs)
        self.textwidget = None

    def attach(self, text_widget):
        self.textwidget = text_widget

    def redraw(self, *args):
        """重新绘制行号"""
        self.delete("all")
        i = self.textwidget.index("@0,0")
        while True :
            dline= self.textwidget.dlineinfo(i)
            if dline is None: break
            y = dline[1]
            linenum = str(i).split(".")[0]
            self.create_text(2, y, anchor="nw", text=linenum, fill="#606366")
            i = self.textwidget.index(f"{i}+1line")

class CodeEditor(tk.Text):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.linenumbers = LineNumbers(self, width=40)
        self.linenumbers.attach(self)

        self.frame = tk.Frame(self.master)
        self.frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.linenumbers.pack(side=tk.LEFT, fill=tk.Y)
        self.pack(in_=self.frame, side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.bind("<<Modified>>", self._on_change)
        self.bind("<Configure>", self._on_change)

        self.lexer = get_lexer_by_name("python")
        self.highlight_job = None
        self.bind("<KeyRelease>", self.on_key_release)

    def on_key_release(self, event=None):
        if self.highlight_job:
            self.after_cancel(self.highlight_job)
        self.highlight_job = self.after(500, self.highlight)

    def highlight(self):
        code = self.get("1.0", "end-1c")
        self.mark_set("range_start", "1.0")
        for token, content in lex(code, self.lexer):
            self.mark_set("range_end", f"range_start + {len(content)}c")
            self.tag_add(str(token), "range_start", "range_end")
            self.mark_set("range_start", "range_end")

    def tag_configure_from_style(self):
        for token, style in self.style:
            foreground = style['color']
            if foreground:
                self.tag_configure(str(token), foreground=f"#{foreground}")

    def set_style(self, style_name):
        self.style = get_style_by_name(style_name)
        self.tag_configure_from_style()
        self.highlight()

    def _on_change(self, event):
        self.linenumbers.redraw()
        self.edit_modified(False)

class AICodeEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("AI代码编辑器")
        self.root.geometry("1600x900")

        self.api_key = "AIzaSyB3QcTs7oN_fKGEQaKc0WBxEpT7OEG_eHs"

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-pro-latest')

        self.config_file = "editor_config.json"
        self.file_list = []
        self.file_contents = {}
        self.current_file = None
        self.main_program = None
        self.chat_history = []
        self.running_process = None
        self.running_file_path = None
        self.error_pattern = re.compile(r'File "([^"]+)", line (\d+)')

        self.load_config()
        self.create_ui()
        self.load_saved_files()
        self.apply_theme()

    def apply_theme(self):
        theme = 'dark' if darkdetect.isDark() else 'light'
        if theme == 'dark':
            self.root.configure(bg="#2b2b2b")
            style = ttk.Style()
            style.theme_use('clam')
            style.configure('.', background='#2b2b2b', foreground='white')
            style.configure('TFrame', background='#2b2b2b')
            style.configure('TLabel', background='#2b2b2b', foreground='white')
            style.configure('TButton', background='#3c3f41', foreground='white')
            style.map('TButton', background=[('active', '#4e5254')])
            style.configure('Accent.TButton', background='#007acc', foreground='white')
            style.map('Accent.TButton', background=[('active', '#005f9e')])

            self.code_text.set_style("monokai")
            self.code_text.configure(bg="#272822", fg="#f8f8f2", insertbackground="white")
            self.console_text.configure(bg="#1e1e1e", fg="#d4d4d4", insertbackground="white")
            self.file_listbox.configure(bg="#3c3f41", fg="white", selectbackground="#007acc")
            self.chat_display.configure(bg="#3c3f41", fg="white")
            self.chat_input.configure(bg="#3c3f41", fg="white", insertbackground="white")
        else: # light theme
            self.root.configure(bg="#ffffff")
            style = ttk.Style()
            style.theme_use('clam')
            style.configure('.', background='#ffffff', foreground='black')
            style.configure('TFrame', background='#ffffff')
            style.configure('TLabel', background='#ffffff', foreground='black')
            style.configure('TButton', background='#f0f0f0', foreground='black')
            style.map('TButton', background=[('active', '#e0e0e0')])
            style.configure('Accent.TButton', background='#0078d7', foreground='white')
            style.map('Accent.TButton', background=[('active', '#005a9e')])

            self.code_text.set_style("default")
            self.code_text.configure(bg="white", fg="black", insertbackground="black")
            self.console_text.configure(bg="white", fg="black", insertbackground="black")
            self.file_listbox.configure(bg="white", fg="black", selectbackground="#0078d7")
            self.chat_display.configure(bg="#f0f0f0", fg="black")
            self.chat_input.configure(bg="white", fg="black", insertbackground="black")

    def create_ui(self):
        main_container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_frame = ttk.Frame(main_container, width=250)
        main_container.add(left_frame, weight=1)

        file_header = ttk.Frame(left_frame)
        file_header.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(file_header, text="项目文件", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
        btn_frame = ttk.Frame(file_header)
        btn_frame.pack(side=tk.RIGHT)

        ttk.Button(btn_frame, text="➕", width=3, command=self.add_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="📁", width=3, command=self.add_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑", width=3, command=self.remove_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🔄", width=3, command=self.reload_all).pack(side=tk.LEFT, padx=2)

        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Consolas", 10))
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_listbox.bind('<<ListboxSelect>>', self.on_file_select)
        self.file_listbox.bind('<Button-3>', self.show_file_context_menu)

        scrollbar.config(command=self.file_listbox.yview)

        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="设为主程序", command=self.set_as_main)
        self.file_context_menu.add_command(label="运行此文件", command=self.run_selected_file)

        self.main_program_label = ttk.Label(left_frame, text="主程序: 未设置", font=("Arial", 9), foreground="blue")
        self.main_program_label.pack(fill=tk.X, padx=5, pady=5)

        right_container = ttk.PanedWindow(main_container, orient=tk.VERTICAL)
        main_container.add(right_container, weight=4)

        code_frame = ttk.LabelFrame(right_container, text="代码编辑区", padding=10)
        right_container.add(code_frame, weight=2)

        self.code_text = CodeEditor(code_frame, wrap=tk.NONE,
                                     font=("Consolas", 11),
                                     undo=True, maxundo=-1, autoseparators=True)
        self.code_text.tag_configure("highlight", background="#444444")

        code_btn_frame = ttk.Frame(code_frame)
        code_btn_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Button(code_btn_frame, text="💾 保存", command=self.save_current_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(code_btn_frame, text="撤销", command=self.undo).pack(side=tk.LEFT, padx=5)
        ttk.Button(code_btn_frame, text="重做", command=self.redo).pack(side=tk.LEFT, padx=5)

        run_frame = ttk.LabelFrame(code_btn_frame, text="运行控制", padding=5)
        run_frame.pack(side=tk.LEFT, padx=20)

        self.run_btn = ttk.Button(run_frame, text="▶ 运行主程序", command=self.run_main_program, style="Accent.TButton")
        self.run_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(run_frame, text="⏹ 停止", command=self.stop_program, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(run_frame, text="🗑 清空输出", command=self.clear_console).pack(side=tk.LEFT, padx=5)

        console_frame = ttk.LabelFrame(right_container, text="输出控制台", padding=10)
        right_container.add(console_frame, weight=1)

        self.console_text = scrolledtext.ScrolledText(console_frame, wrap=tk.WORD, font=("Consolas", 10))
        self.console_text.pack(fill=tk.BOTH, expand=True)

        self.console_text.tag_config("error", foreground="#ff5555")
        self.console_text.tag_config("info", foreground="#50fa7b")
        self.console_text.tag_config("warning", foreground="#ffb86c")
        self.console_text.tag_config("file_link", foreground="#6897bb", underline=True)
        self.console_text.tag_bind("file_link", "<Button-1>", self.on_error_click)
        self.console_text.tag_bind("file_link", "<Enter>", lambda e: self.console_text.config(cursor="hand2"))
        self.console_text.tag_bind("file_link", "<Leave>", lambda e: self.console_text.config(cursor=""))

        chat_frame = ttk.LabelFrame(right_container, text="AI助手", padding=10)
        right_container.add(chat_frame, weight=2)

        self.chat_display = scrolledtext.ScrolledText(chat_frame, wrap=tk.WORD, font=("Arial", 10), state=tk.DISABLED)
        self.chat_display.pack(fill=tk.BOTH, expand=True)

        input_frame = ttk.Frame(chat_frame)
        input_frame.pack(fill=tk.X, pady=(10, 0))

        self.chat_input = scrolledtext.ScrolledText(input_frame, wrap=tk.WORD, font=("Arial", 10), height=3)
        self.chat_input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        btn_container = ttk.Frame(input_frame)
        btn_container.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Button(btn_container, text="发送\n(Ctrl+Enter)", command=self.send_to_ai).pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        ttk.Button(btn_container, text="分析所有\n文件", command=self.analyze_all_files).pack(fill=tk.BOTH, expand=True)

        self.chat_input.bind('<Control-Return>', lambda e: self.send_to_ai())
        self.root.bind('<F5>', lambda e: self.run_main_program())
        self.root.bind('<Control-s>', lambda e: self.save_current_file())
        self.root.bind('<Control-z>', lambda e: self.undo())
        self.root.bind('<Control-y>', lambda e: self.redo())

    def undo(self):
        try:
            self.code_text.edit_undo()
        except tk.TclError:
            pass

    def redo(self):
        try:
            self.code_text.edit_redo()
        except tk.TclError:
            pass

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.file_list = config.get('files', [])
                    self.main_program = config.get('main_program', None)
            except Exception as e:
                print(f"加载配置失败: {e}")

    def save_config(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({'files': self.file_list, 'main_program': self.main_program}, f, ensure_ascii=False, indent=2)
            self.update_main_program_label()
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")

    def add_file(self):
        files = filedialog.askopenfilenames(filetypes=[("Python文件", "*.py"), ("文本文件", "*.txt"), ("所有文件", "*.*")])
        for file in files:
            if file not in self.file_list:
                self.file_list.append(file)
                self.load_file_content(file)
        self.update_file_list()
        self.save_config()

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.endswith('.py'):
                        full_path = os.path.join(root, file)
                        if full_path not in self.file_list:
                            self.file_list.append(full_path)
                            self.load_file_content(full_path)
            self.update_file_list()
            self.save_config()
            messagebox.showinfo("成功", f"已添加文件夹: {folder}")

    def remove_file(self):
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
            file_path = self.file_list[idx]
            if file_path == self.main_program: self.main_program = None
            self.file_list.pop(idx)
            if file_path in self.file_contents: del self.file_contents[file_path]
            self.update_file_list()
            self.save_config()
            self.code_text.delete(1.0, tk.END)
            self.current_file = None

    def load_file_content(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.file_contents[file_path] = f.read()
        except Exception as e:
            messagebox.showerror("错误", f"读取文件失败 {file_path}: {e}")

    def load_saved_files(self):
        for file_path in self.file_list[:]:
            if os.path.exists(file_path):
                self.load_file_content(file_path)
            else:
                self.file_list.remove(file_path)
        self.update_file_list()
        self.update_main_program_label()
        if self.file_list:
            self.console_print(f"已加载 {len(self.file_list)} 个文件", "info")

    def reload_all(self):
        for file_path in self.file_list: self.load_file_content(file_path)
        messagebox.showinfo("成功", "所有文件已重新加载")

    def update_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for file_path in self.file_list:
            display_name = Path(file_path).name
            if file_path == self.main_program: display_name = "⭐ " + display_name
            self.file_listbox.insert(tk.END, display_name)

    def update_main_program_label(self):
        if self.main_program:
            self.main_program_label.config(text=f"主程序: {Path(self.main_program).name}")
        else:
            self.main_program_label.config(text="主程序: 未设置")

    def on_file_select(self, event):
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
            file_path = self.file_list[idx]
            self.current_file = file_path
            self.code_text.delete(1.0, tk.END)
            if file_path in self.file_contents:
                self.code_text.insert(1.0, self.file_contents[file_path])
                self.code_text.edit_reset()
                self.code_text.edit_modified(False)
                self.code_text.highlight()

    def show_file_context_menu(self, event):
        idx = self.file_listbox.nearest(event.y)
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(idx)
        self.file_listbox.activate(idx)
        self.file_context_menu.post(event.x_root, event.y_root)

    def set_as_main(self):
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
            self.main_program = self.file_list[idx]
            self.save_config()
            self.update_file_list()
            self.console_print(f"已设置主程序: {Path(self.main_program).name}", "info")

    def run_selected_file(self):
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
            file_path = self.file_list[idx]
            self.run_python_file(file_path)

    def save_current_file(self):
        if not self.current_file:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        try:
            content = self.code_text.get(1.0, tk.END)[:-1]
            with open(self.current_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.file_contents[self.current_file] = content
            self.console_print(f"文件已保存: {Path(self.current_file).name}", "info")
            self.code_text.edit_modified(False)
        except Exception as e:
            messagebox.showerror("错误", f"保存文件失败: {e}")

    def console_print(self, message, tag="normal"):
        for line in message.splitlines():
            match = self.error_pattern.search(line)
            if match:
                start, end = match.span()
                self.console_text.insert(tk.END, line[:start])
                self.console_text.insert(tk.END, line[start:end], ("file_link", tag))
                self.console_text.insert(tk.END, line[end:] + "\n")
            else:
                self.console_text.insert(tk.END, line + "\n", tag)
        self.console_text.see(tk.END)
        self.root.update()

    def on_error_click(self, event):
        index = self.console_text.index(f"@{event.x},{event.y}")
        tag_indices = self.console_text.tag_ranges("file_link")
        for start, end in zip(tag_indices[0::2], tag_indices[1::2]):
            if self.console_text.compare(index, ">=", start) and self.console_text.compare(index, "<=", end):
                line_text = self.console_text.get(start, end)
                match = self.error_pattern.search(line_text)
                if match:
                    file_path, line_number = match.groups()
                    if not os.path.isabs(file_path) and self.running_file_path:
                        work_dir = os.path.dirname(self.running_file_path)
                        full_path = os.path.abspath(os.path.join(work_dir, file_path))
                    else:
                        full_path = file_path
                    self.jump_to_file(full_path, int(line_number))
                break

    def jump_to_file(self, file_path, line_number):
        file_path = os.path.normpath(file_path)
        if file_path not in self.file_list:
            messagebox.showinfo("信息", f"文件 {Path(file_path).name} 不在当前项目列表中。")
            return
        idx = self.file_list.index(file_path)
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(idx)
        self.file_listbox.see(idx)
        self.on_file_select(None)
        self.root.after(100, lambda: self._scroll_and_highlight(line_number))

    def _scroll_and_highlight(self, line_number):
        self.code_text.see(f"{line_number}.0")
        self.code_text.tag_remove("highlight", "1.0", tk.END)
        line_start = f"{line_number}.0"
        line_end = f"{line_number}.end"
        self.code_text.tag_add("highlight", line_start, line_end)

    def clear_console(self):
        self.console_text.delete(1.0, tk.END)

    def run_main_program(self):
        if not self.main_program:
            messagebox.showwarning("警告", "请先右键点击文件设置主程序")
            return
        if not os.path.exists(self.main_program):
            messagebox.showerror("错误", "主程序文件不存在")
            return
        self.run_python_file(self.main_program)

    def run_python_file(self, file_path):
        if self.running_process:
            messagebox.showwarning("警告", "已有程序在运行,请先停止")
            return
        self.running_file_path = file_path
        self.console_print("="*60, "info")
        self.console_print(f"▶ 运行: {Path(file_path).name}", "info")
        self.console_print("="*60, "info")
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        thread = threading.Thread(target=self._run_process, args=(file_path,))
        thread.daemon = True
        thread.start()

    def _run_process(self, file_path):
        try:
            work_dir = os.path.dirname(file_path)
            self.running_process = subprocess.Popen(
                [sys.executable, file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=work_dir, bufsize=1, universal_newlines=True)
            for line in self.running_process.stdout:
                self.console_print(line.rstrip(), "normal")
            self.running_process.wait()
            stderr = self.running_process.stderr.read()
            if stderr:
                self.console_print(stderr, "error")
            exit_code = self.running_process.returncode
            msg = f"\n✓ 程序执行完成 (退出码: {exit_code})" if exit_code == 0 else f"\n✗ 程序异常退出 (退出码: {exit_code})"
            tag = "info" if exit_code == 0 else "error"
            self.console_print(msg, tag)
        except Exception as e:
            self.console_print(f"\n✗ 运行出错: {e}", "error")
        finally:
            self.running_process = None
            self.running_file_path = None
            self.root.after(0, self._restore_run_buttons)

    def _restore_run_buttons(self):
        self.run_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def stop_program(self):
        if self.running_process:
            try:
                self.running_process.terminate()
                self.running_process.wait(timeout=3)
                self.console_print("\n⏹ 程序已停止", "warning")
            except:
                self.running_process.kill()
                self.console_print("\n⏹ 程序已强制终止", "warning")
            finally:
                self.running_process = None
                self._restore_run_buttons()

    def add_chat_message(self, role, message):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"\n{'='*60}\n{role}:\n", "role")
        self.chat_display.insert(tk.END, f"{message}\n")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

    def send_to_ai(self):
        user_message = self.chat_input.get(1.0, tk.END).strip()
        if not user_message: return
        self.chat_input.delete(1.0, tk.END)
        self.add_chat_message("你", user_message)
        context = self.build_context(user_message)
        try:
            response = self.model.generate_content(context)
            ai_response = response.text
            self.add_chat_message("AI", ai_response)
            if "```python" in ai_response and self.current_file:
                if messagebox.askyesno("应用更改", "AI提供了代码建议,是否应用到当前文件?"):
                    self.apply_ai_suggestion(ai_response)
        except Exception as e:
            self.add_chat_message("错误", f"AI请求失败: {e}")

    def build_context(self, user_message):
        context = f"用户问题: {user_message}\n\n"
        if self.current_file:
            context += f"当前文件: {Path(self.current_file).name}\n文件内容:\n```python\n{self.file_contents.get(self.current_file, '')}\n```\n\n"
        context += "请帮我分析或修改代码。如果需要修改代码,请用```python代码块格式提供完整的修改后的代码。"
        return context

    def analyze_all_files(self):
        if not self.file_list:
            messagebox.showwarning("警告", "没有文件可分析")
            return
        self.add_chat_message("系统", "开始分析所有文件...")
        context = "请分析以下项目中的所有Python文件,给出代码质量评估和改进建议:\n\n"
        for file_path in self.file_list:
            if file_path.endswith('.py'):
                context += f"文件: {Path(file_path).name}\n```python\n{self.file_contents.get(file_path, '')}\n```\n\n"
        try:
            response = self.model.generate_content(context)
            self.add_chat_message("AI分析", response.text)
        except Exception as e:
            self.add_chat_message("错误", f"分析失败: {e}")

    def apply_ai_suggestion(self, ai_response):
        code_blocks = re.findall(r'```python\n(.*?)```', ai_response, re.DOTALL)
        if code_blocks:
            self.code_text.delete(1.0, tk.END)
            self.code_text.insert(1.0, code_blocks[0])
            self.add_chat_message("系统", "已应用AI建议,请检查后保存")

if __name__ == "__main__":
    root = tk.Tk()
    app = AICodeEditor(root)
    root.mainloop()
