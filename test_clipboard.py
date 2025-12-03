# test_clipboard.py
import sys
import os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage, QClipboard
from PyQt5.QtCore import QUrl, QMimeData

def main():
    app = QApplication(sys.argv)

    clipboard = app.clipboard()

    # 1. 模拟复制文本
    print("复制文本...")
    clipboard.setText("这是一段测试文本。")
    app.processEvents() # 确保事件被处理

    # 2. 模拟复制图片 (创建一个简单的黑色图片)
    print("复制图片...")
    image = QImage(100, 100, QImage.Format_RGB32)
    image.fill(0) # 填充为黑色
    clipboard.setImage(image)
    app.processEvents()

    # 3. 模拟复制文件
    print("复制文件...")
    # 创建一个临时文件用于测试
    file_path = os.path.abspath("test_file.tmp")
    with open(file_path, "w") as f:
        f.write("这是一个虚拟文件。")

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(file_path)])
    clipboard.setMimeData(mime_data)
    app.processEvents()

    print("测试完成。")

if __name__ == "__main__":
    main()
