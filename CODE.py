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

class AICodeEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("AI代码编辑器")
        self.root.geometry("1600x900")
        
        # 配置Gemini API
        self.api_key = "AIzaSyB3QcTs7oN_fKGEQaKc0WBxEpT7OEG_eHs"
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        
        # 数据存储
        self.config_file = "editor_config.json"
        self.file_list = []
        self.file_contents = {}
        self.current_file = None
        self.main_program = None  # 主程序入口
        self.chat_history = []
        self.running_process = None  # 当前运行的进程
        
        # 加载配置
        self.load_config()
        
        # 创建UI
        self.create_ui()
        
        # 加载已保存的文件
        self.load_saved_files()
    
    def create_ui(self):
        # 主容器
        main_container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧面板 - 文件列表
        left_frame = ttk.Frame(main_container, width=250)
        main_container.add(left_frame, weight=1)
        
        # 文件列表标题和按钮
        file_header = ttk.Frame(left_frame)
        file_header.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(file_header, text="项目文件", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
        
        btn_frame = ttk.Frame(file_header)
        btn_frame.pack(side=tk.RIGHT)
        
        ttk.Button(btn_frame, text="➕", width=3, command=self.add_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="📁", width=3, command=self.add_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑", width=3, command=self.remove_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🔄", width=3, command=self.reload_all).pack(side=tk.LEFT, padx=2)
        
        # 文件列表
        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.file_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Consolas", 10))
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_listbox.bind('<<ListboxSelect>>', self.on_file_select)
        self.file_listbox.bind('<Button-3>', self.show_file_context_menu)  # 右键菜单
        
        scrollbar.config(command=self.file_listbox.yview)
        
        # 创建右键菜单
        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="设为主程序", command=self.set_as_main)
        self.file_context_menu.add_command(label="运行此文件", command=self.run_selected_file)
        
        # 主程序标签
        self.main_program_label = ttk.Label(left_frame, text="主程序: 未设置", 
                                           font=("Arial", 9), foreground="blue")
        self.main_program_label.pack(fill=tk.X, padx=5, pady=5)
        
        # 右侧面板容器
        right_container = ttk.PanedWindow(main_container, orient=tk.VERTICAL)
        main_container.add(right_container, weight=4)
        
        # 代码编辑区
        code_frame = ttk.LabelFrame(right_container, text="代码编辑区", padding=10)
        right_container.add(code_frame, weight=2)
        
        self.code_text = scrolledtext.ScrolledText(code_frame, wrap=tk.NONE, 
                                                    font=("Consolas", 11),
                                                    bg="#1e1e1e", fg="#d4d4d4",
                                                    insertbackground="white")
        self.code_text.pack(fill=tk.BOTH, expand=True)
        
        # 代码操作按钮
        code_btn_frame = ttk.Frame(code_frame)
        code_btn_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(code_btn_frame, text="💾 保存", command=self.save_current_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(code_btn_frame, text="↩ 撤销更改", command=self.revert_changes).pack(side=tk.LEFT, padx=5)
        
        # 运行控制区
        run_frame = ttk.LabelFrame(code_btn_frame, text="运行控制", padding=5)
        run_frame.pack(side=tk.LEFT, padx=20)
        
        self.run_btn = ttk.Button(run_frame, text="▶ 运行主程序", 
                                  command=self.run_main_program, style="Accent.TButton")
        self.run_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(run_frame, text="⏹ 停止", 
                                   command=self.stop_program, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(run_frame, text="🗑 清空输出", 
                  command=self.clear_console).pack(side=tk.LEFT, padx=5)
        
        # 输出控制台
        console_frame = ttk.LabelFrame(right_container, text="输出控制台", padding=10)
        right_container.add(console_frame, weight=1)
        
        self.console_text = scrolledtext.ScrolledText(console_frame, wrap=tk.WORD, 
                                                      font=("Consolas", 10),
                                                      bg="#0c0c0c", fg="#00ff00",
                                                      insertbackground="white")
        self.console_text.pack(fill=tk.BOTH, expand=True)
        
        # 配置输出样式
        self.console_text.tag_config("error", foreground="#ff5555")
        self.console_text.tag_config("info", foreground="#50fa7b")
        self.console_text.tag_config("warning", foreground="#ffb86c")
        
        # AI对话区
        chat_frame = ttk.LabelFrame(right_container, text="AI助手", padding=10)
        right_container.add(chat_frame, weight=2)
        
        # 对话历史
        self.chat_display = scrolledtext.ScrolledText(chat_frame, wrap=tk.WORD, 
                                                       font=("Arial", 10),
                                                       bg="#f5f5f5", state=tk.DISABLED)
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        
        # 输入区
        input_frame = ttk.Frame(chat_frame)
        input_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.chat_input = scrolledtext.ScrolledText(input_frame, wrap=tk.WORD, 
                                                     font=("Arial", 10), height=3)
        self.chat_input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        btn_container = ttk.Frame(input_frame)
        btn_container.pack(side=tk.RIGHT, fill=tk.Y)
        
        ttk.Button(btn_container, text="发送\n(Ctrl+Enter)", 
                  command=self.send_to_ai).pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        ttk.Button(btn_container, text="分析所有\n文件", 
                  command=self.analyze_all_files).pack(fill=tk.BOTH, expand=True)
        
        # 绑定快捷键
        self.chat_input.bind('<Control-Return>', lambda e: self.send_to_ai())
        self.root.bind('<F5>', lambda e: self.run_main_program())
    
    def load_config(self):
        """加载配置文件"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.file_list = config.get('files', [])
                    self.main_program = config.get('main_program', None)
            except Exception as e:
                print(f"加载配置失败: {e}")
    
    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'files': self.file_list,
                    'main_program': self.main_program
                }, f, ensure_ascii=False, indent=2)
            self.update_main_program_label()
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")
    
    def add_file(self):
        """添加单个文件"""
        files = filedialog.askopenfilenames(
            title="选择文件",
            filetypes=[("Python文件", "*.py"), ("文本文件", "*.txt"), 
                      ("所有文件", "*.*")]
        )
        for file in files:
            if file not in self.file_list:
                self.file_list.append(file)
                self.load_file_content(file)
        
        self.update_file_list()
        self.save_config()
    
    def add_folder(self):
        """添加文件夹中的所有Python文件"""
        folder = filedialog.askdirectory(title="选择文件夹")
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
        """移除选中的文件"""
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
            file_path = self.file_list[idx]
            
            # 如果删除的是主程序,清除主程序设置
            if file_path == self.main_program:
                self.main_program = None
            
            self.file_list.pop(idx)
            if file_path in self.file_contents:
                del self.file_contents[file_path]
            
            self.update_file_list()
            self.save_config()
            self.code_text.delete(1.0, tk.END)
            self.current_file = None
    
    def load_file_content(self, file_path):
        """加载文件内容"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.file_contents[file_path] = f.read()
        except Exception as e:
            messagebox.showerror("错误", f"读取文件失败 {file_path}: {e}")
    
    def load_saved_files(self):
        """加载所有已保存的文件"""
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
        """重新加载所有文件"""
        for file_path in self.file_list:
            self.load_file_content(file_path)
        messagebox.showinfo("成功", "所有文件已重新加载")
    
    def update_file_list(self):
        """更新文件列表显示"""
        self.file_listbox.delete(0, tk.END)
        for file_path in self.file_list:
            display_name = Path(file_path).name
            if file_path == self.main_program:
                display_name = "⭐ " + display_name
            self.file_listbox.insert(tk.END, display_name)
    
    def update_main_program_label(self):
        """更新主程序标签"""
        if self.main_program:
            self.main_program_label.config(
                text=f"主程序: {Path(self.main_program).name}"
            )
        else:
            self.main_program_label.config(text="主程序: 未设置")
    
    def on_file_select(self, event):
        """文件选择事件"""
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
            file_path = self.file_list[idx]
            self.current_file = file_path
            
            # 显示文件内容
            self.code_text.delete(1.0, tk.END)
            if file_path in self.file_contents:
                self.code_text.insert(1.0, self.file_contents[file_path])
    
    def show_file_context_menu(self, event):
        """显示文件右键菜单"""
        # 选中右键点击的项
        idx = self.file_listbox.nearest(event.y)
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(idx)
        self.file_listbox.activate(idx)
        
        # 显示菜单
        self.file_context_menu.post(event.x_root, event.y_root)
    
    def set_as_main(self):
        """设置选中文件为主程序"""
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
            self.main_program = self.file_list[idx]
            self.save_config()
            self.update_file_list()
            self.console_print(f"已设置主程序: {Path(self.main_program).name}", "info")
    
    def run_selected_file(self):
        """运行选中的文件"""
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
            file_path = self.file_list[idx]
            self.run_python_file(file_path)
    
    def save_current_file(self):
        """保存当前文件"""
        if not self.current_file:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        try:
            content = self.code_text.get(1.0, tk.END)[:-1]  # 去除最后的换行
            with open(self.current_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.file_contents[self.current_file] = content
            self.console_print(f"文件已保存: {Path(self.current_file).name}", "info")
        except Exception as e:
            messagebox.showerror("错误", f"保存文件失败: {e}")
    
    def revert_changes(self):
        """撤销更改"""
        if self.current_file and self.current_file in self.file_contents:
            self.code_text.delete(1.0, tk.END)
            self.code_text.insert(1.0, self.file_contents[self.current_file])
    
    def console_print(self, message, tag="normal"):
        """在控制台打印消息"""
        self.console_text.insert(tk.END, message + "\n", tag)
        self.console_text.see(tk.END)
        self.root.update()
    
    def clear_console(self):
        """清空控制台"""
        self.console_text.delete(1.0, tk.END)
    
    def run_main_program(self):
        """运行主程序"""
        if not self.main_program:
            messagebox.showwarning("警告", "请先右键点击文件设置主程序")
            return
        
        if not os.path.exists(self.main_program):
            messagebox.showerror("错误", "主程序文件不存在")
            return
        
        self.run_python_file(self.main_program)
    
    def run_python_file(self, file_path):
        """在新线程中运行Python文件"""
        if self.running_process:
            messagebox.showwarning("警告", "已有程序在运行,请先停止")
            return
        
        self.console_print("="*60, "info")
        self.console_print(f"▶ 运行: {Path(file_path).name}", "info")
        self.console_print("="*60, "info")
        
        # 禁用运行按钮,启用停止按钮
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        # 在新线程中运行
        thread = threading.Thread(target=self._run_process, args=(file_path,))
        thread.daemon = True
        thread.start()
    
    def _run_process(self, file_path):
        """实际执行Python进程"""
        try:
            # 获取文件所在目录
            work_dir = os.path.dirname(file_path)
            
            # 创建子进程
            self.running_process = subprocess.Popen(
                [sys.executable, file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=work_dir,
                bufsize=1,
                universal_newlines=True
            )
            
            # 读取输出
            for line in self.running_process.stdout:
                self.console_print(line.rstrip(), "normal")
            
            # 等待进程结束
            self.running_process.wait()
            
            # 读取错误输出
            stderr = self.running_process.stderr.read()
            if stderr:
                self.console_print(stderr, "error")
            
            # 显示退出码
            exit_code = self.running_process.returncode
            if exit_code == 0:
                self.console_print(f"\n✓ 程序执行完成 (退出码: {exit_code})", "info")
            else:
                self.console_print(f"\n✗ 程序异常退出 (退出码: {exit_code})", "error")
        
        except Exception as e:
            self.console_print(f"\n✗ 运行出错: {e}", "error")
        
        finally:
            self.running_process = None
            # 恢复按钮状态
            self.root.after(0, self._restore_run_buttons)
    
    def _restore_run_buttons(self):
        """恢复运行按钮状态"""
        self.run_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
    
    def stop_program(self):
        """停止正在运行的程序"""
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
        """添加聊天消息"""
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"\n{'='*60}\n")
        self.chat_display.insert(tk.END, f"{role}:\n", "role")
        self.chat_display.insert(tk.END, f"{message}\n")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
    
    def send_to_ai(self):
        """发送消息到AI"""
        user_message = self.chat_input.get(1.0, tk.END).strip()
        if not user_message:
            return
        
        self.chat_input.delete(1.0, tk.END)
        self.add_chat_message("你", user_message)
        
        # 构建上下文
        context = self.build_context(user_message)
        
        try:
            response = self.model.generate_content(context)
            ai_response = response.text
            self.add_chat_message("AI", ai_response)
            
            # 如果AI建议修改代码,询问是否应用
            if "```python" in ai_response and self.current_file:
                if messagebox.askyesno("应用更改", "AI提供了代码建议,是否应用到当前文件?"):
                    self.apply_ai_suggestion(ai_response)
        
        except Exception as e:
            self.add_chat_message("错误", f"AI请求失败: {e}")
    
    def build_context(self, user_message):
        """构建发送给AI的上下文"""
        context = f"用户问题: {user_message}\n\n"
        
        if self.current_file:
            context += f"当前文件: {Path(self.current_file).name}\n"
            context += f"文件内容:\n```python\n{self.file_contents.get(self.current_file, '')}\n```\n\n"
        
        context += "请帮我分析或修改代码。如果需要修改代码,请用```python代码块格式提供完整的修改后的代码。"
        return context
    
    def analyze_all_files(self):
        """让AI分析所有文件"""
        if not self.file_list:
            messagebox.showwarning("警告", "没有文件可分析")
            return
        
        self.add_chat_message("系统", "开始分析所有文件...")
        
        context = "请分析以下项目中的所有Python文件,给出代码质量评估和改进建议:\n\n"
        
        for file_path in self.file_list:
            if file_path.endswith('.py'):
                context += f"文件: {Path(file_path).name}\n"
                context += f"```python\n{self.file_contents.get(file_path, '')}\n```\n\n"
        
        try:
            response = self.model.generate_content(context)
            self.add_chat_message("AI分析", response.text)
        except Exception as e:
            self.add_chat_message("错误", f"分析失败: {e}")
    
    def apply_ai_suggestion(self, ai_response):
        """应用AI建议的代码"""
        # 提取代码块
        import re
        code_blocks = re.findall(r'```python\n(.*?)```', ai_response, re.DOTALL)
        
        if code_blocks:
            self.code_text.delete(1.0, tk.END)
            self.code_text.insert(1.0, code_blocks[0])
            self.add_chat_message("系统", "已应用AI建议,请检查后保存")

if __name__ == "__main__":
    root = tk.Tk()
    app = AICodeEditor(root)
    root.mainloop()
