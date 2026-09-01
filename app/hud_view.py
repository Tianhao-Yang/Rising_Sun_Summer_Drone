from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


class HudView(QLabel):

    def __init__(self):
        super().__init__()

        # Keep the HUD aligned to the left.
        self.setAlignment(
            Qt.AlignLeft | Qt.AlignTop
        )

        # Do not force a black background.
        self.setStyleSheet(
            "background-color: transparent;"
        )

        # Let the layout decide how much space this widget receives.
        self.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Expanding,
        )

        self._pixmap = None

        # Original HUD frame size
        self._frame_width = 0
        self._frame_height = 0


    # =========================
    # Receive OpenCV frame
    # =========================

    def set_frame(self, frame):

        if frame is None:
            return

        height, width, channels = frame.shape

        # Save original frame dimensions.
        self._frame_width = width
        self._frame_height = height

        bytes_per_line = (
            channels * width
        )

        # OpenCV frame is BGR.
        image = QImage(
            frame.data,
            width,
            height,
            bytes_per_line,
            QImage.Format_BGR888,
        ).copy()

        self._pixmap = QPixmap.fromImage(
            image
        )

        self._update_display()

        # Tell the layout system that our preferred size may have changed.
        self.updateGeometry()


    # =========================
    # Aspect ratio
    # =========================

    def aspect_ratio(self):

        if (
            self._frame_width <= 0
            or self._frame_height <= 0
        ):
            return 16 / 9

        return (
            self._frame_width
            / self._frame_height
        )


    # =========================
    # Preferred size
    # =========================

    def sizeHint(self):

        # Before a real camera frame arrives,
        # use a reasonable 16:9 placeholder.
        if (
            self._frame_width <= 0
            or self._frame_height <= 0
        ):
            return QSize(
                960,
                540,
            )

        return QSize(
            self._frame_width,
            self._frame_height,
        )


    # =========================
    # Resize
    # =========================

    def resizeEvent(self, event):

        super().resizeEvent(event)

        self._update_display()


    # =========================
    # Draw scaled HUD
    # =========================

    def _update_display(self):

        if self._pixmap is None:
            return

        # Scale while preserving the original HUD ratio.
        scaled_pixmap = self._pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        self.setPixmap(
            scaled_pixmap
        )