import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow

def main():

    # Create the Qt application
    app = QApplication(sys.argv)

    # Create our main window
    window = MainWindow()

    # Show the window
    window.showFullScreen()

    # Start the Qt event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()  