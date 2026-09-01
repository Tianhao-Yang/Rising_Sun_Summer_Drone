from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QPainter,
    QPen,
    QColor,
    QFont,
    QFontDatabase,
)

from PySide6.QtWidgets import QWidget


class LogoWidget(QWidget):

    def __init__(self):
        super().__init__()

        # Size of the logo area
        self.setFixedSize(
            180,
            50,
        )

        # Default font
        self.logo_font = QFont()

        # =========================
        # Try to load custom font
        # =========================

        project_root = (
            Path(__file__).resolve().parent.parent
        )

        font_path = (
            project_root
            / "assets"
            / "ZhiMangXing-Regular.ttf"
        )

        if font_path.exists():

            font_id = QFontDatabase.addApplicationFont(
                str(font_path)
            )

            if font_id != -1:

                families = (
                    QFontDatabase.applicationFontFamilies(
                        font_id
                    )
                )

                if families:

                    self.logo_font = QFont(
                        families[0]
                    )

        # Font size
        self.logo_font.setPointSize(20)


    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        painter.setRenderHint(
            QPainter.TextAntialiasing
        )


        # =========================
        # Text color
        # =========================

        painter.setPen(
            QPen(
                QColor(
                    196,
                    0,
                    0,
                )
            )
        )


        # =========================
        # Font
        # =========================

        painter.setFont(
            self.logo_font
        )


        # =========================
        # Draw logo text
        # =========================
        text_rect = self.rect()
        text_rect.translate(0, -3)
        
        painter.drawText(
            self.rect(),
            Qt.AlignLeft | Qt.AlignVCenter,
            "红太阳一号",
        )