
import sys
import time
import subprocess
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QMimeData, QUrl
from PyQt5.QtGui import QImage, QPixmap

def copy_text_to_clipboard(text):
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    clipboard = app.clipboard()
    mime_data = QMimeData()
    mime_data.setText(text)
    clipboard.setMimeData(mime_data, mode=clipboard.Clipboard)
    print(f"'{text}' copied to clipboard.")

def copy_image_to_clipboard(image_path):
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    clipboard = app.clipboard()
    image = QImage(image_path)
    if image.isNull():
        print(f"Error: Failed to load image from {image_path}")
        return
    pixmap = QPixmap.fromImage(image)
    clipboard.setPixmap(pixmap, mode=clipboard.Clipboard)
    print(f"Image '{image_path}' copied to clipboard.")

def copy_file_to_clipboard(file_path):
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    clipboard = app.clipboard()
    mime_data = QMimeData()
    url = QUrl.fromLocalFile(file_path)
    mime_data.setUrls([url])
    clipboard.setMimeData(mime_data, mode=clipboard.Clipboard)
    print(f"File '{file_path}' copied to clipboard.")

def main():
    # 1. Start the main application in the background
    # Ensure any previous instances are killed to avoid conflicts
    subprocess.run("pkill -9 -f Xvfb; pkill -9 -f CODE.py; rm -f /tmp/.X99-lock", shell=True)
    time.sleep(1)

    # Start virtual framebuffer
    xvfb_process = subprocess.Popen("Xvfb :99 -screen 0 1600x1200x24 &", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1)

    # Set environment variables for PyQt
    command = (
        'export DISPLAY=:99; '
        'export QT_QPA_PLATFORM_PLUGIN_PATH=$(find / -name "libqxcb.so" 2>/dev/null | sed "s|/libqxcb.so||"); '
        'python3 CODE.py &> app.log &'
    )
    main_app_process = subprocess.Popen(command, shell=True, executable='/bin/bash')

    # Wait for the main application to initialize
    print("Waiting for application to start...")
    time.sleep(5)

    # 2. Simulate clipboard operations
    print("\n--- Starting Clipboard Simulation ---")

    # Create a dummy file for file copy simulation
    with open("dummy_test_file.txt", "w") as f:
        f.write("This is a test file for clipboard simulation.")

    # Create a dummy image file (a simple 1x1 red pixel PNG)
    from PIL import Image
    img = Image.new('RGB', (10, 10), color = 'red')
    img.save('dummy_test_image.png')

    # Execute copy functions
    app = QApplication(sys.argv) # Create a single QApplication instance for the script
    copy_text_to_clipboard("Hello, this is a text test.")
    time.sleep(2) # Give the app time to process

    copy_image_to_clipboard("dummy_test_image.png")
    time.sleep(2)

    copy_file_to_clipboard("dummy_test_file.txt")
    time.sleep(2)

    print("--- Clipboard Simulation Finished ---\n")

    # 3. Take a final screenshot for verification
    print("Taking final screenshot...")
    subprocess.run("export DISPLAY=:99; scrot final_verification.png", shell=True)
    time.sleep(1)

    # 4. Clean up
    print("Cleaning up...")
    main_app_process.kill()
    xvfb_process.kill()
    subprocess.run("rm dummy_test_file.txt dummy_test_image.png", shell=True)

    print("\nVerification script finished. Check 'final_verification.png' and 'app.log'.")

if __name__ == "__main__":
    main()
