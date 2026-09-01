from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class AlertItemWidget(QFrame):
    """One responsive warning or critical alert row."""

    def __init__(self, severity, text, details="", parent=None):
        super().__init__(parent)

        severity = str(severity).upper()
        critical = severity == "CRITICAL"
        color = "#D71920" if critical else "#D69E00"
        background = "#FFF0F0" if critical else "#FFF8D8"

        self.setStyleSheet(
            "QFrame {"
            f"background-color: {background};"
            f"border-left: 4px solid {color};"
            "border-radius: 3px;"
            "}"
        )

        severity_label = QLabel(severity)
        severity_label.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: 700;"
            "background: transparent; border: none;"
        )

        text_label = QLabel(str(text))
        text_label.setWordWrap(True)
        text_label.setStyleSheet(
            "color: #202020; font-size: 11px; font-weight: 600;"
            "background: transparent; border: none;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(2)
        layout.addWidget(severity_label)
        layout.addWidget(text_label)

        if details:
            details_label = QLabel(str(details))
            details_label.setWordWrap(True)
            details_label.setStyleSheet(
                "color: #606060; font-size: 9px;"
                "background: transparent; border: none;"
            )
            layout.addWidget(details_label)