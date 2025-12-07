import os
import tkinter as tk
from tkinter import filedialog, messagebox

def process_python_files_in_folder():
    """
    打开一个文件夹选择对话框,读取选定文件夹及其所有子文件夹中
    所有 .py 文件的内容,并将内容合并写入到一个新的 txt 文件中。
    """
    # 打开文件夹选择对话框
    folder_path = filedialog.askdirectory()

    # 如果用户没有选择文件夹,则直接返回
    if not folder_path:
        return

    # 定义输出文件的名称
    output_filename = "combined_py_code.txt"
    # 将输出文件路径设置在脚本所在的根目录下
    output_filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_filename)

    try:
        # 收集所有 .py 文件的路径
        python_files = []
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(".py"):
                    python_files.append(os.path.join(root, file))

        # 如果没有找到 .py 文件,则通知用户并退出
        if not python_files:
            messagebox.showinfo("提示", f"在文件夹 '{folder_path}' 中没有找到任何 .py 文件。")
            return

        # 读取所有 .py 文件的内容并写入到输出文件中
        with open(output_filepath, 'w', encoding='utf-8') as outfile:
            # 对文件路径进行排序,以确保输出内容具有一致的顺序
            for filepath in sorted(python_files):
                try:
                    with open(filepath, 'r', encoding='utf-8') as infile:
                        outfile.write(f"# --- Start of content from: {filepath} ---\n")
                        outfile.write(infile.read())
                        outfile.write(f"\n# --- End of content from: {filepath} ---\n\n")
                except Exception as e:
                    # 如果读取某个文件失败,则在输出文件中记录一条错误信息
                    outfile.write(f"# --- Error reading file: {filepath} ---\n")
                    outfile.write(f"# Error: {e}\n")
                    outfile.write(f"# --- End of error log ---\n\n")

        # 操作成功后,弹出消息框通知用户
        messagebox.showinfo("成功", f"所有 .py 文件的内容已成功合并到文件:\n{output_filepath}")

    except Exception as e:
        # 如果在过程中发生任何其他错误,则显示错误消息
        messagebox.showerror("错误", f"处理过程中发生错误:\n{e}")

# --- 创建主窗口 ---
def main():
    """主函数,用于设置并启动GUI应用程序"""
    root = tk.Tk()
    root.title("Python 文件内容合并工具")
    root.geometry("500x200")

    # --- 创建UI元素 ---
    # 提示标签
    info_label = tk.Label(root, text="请点击下方的按钮,然后选择一个文件夹。")
    info_label.pack(pady=20)

    # 处理按钮
    process_button = tk.Button(root, text="选择文件夹并开始处理", command=process_python_files_in_folder)
    process_button.pack(pady=20)

    # --- 启动主事件循环 ---
    root.mainloop()

if __name__ == "__main__":
    main()
