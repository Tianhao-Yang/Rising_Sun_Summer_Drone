from pathlib import Path
from html import escape

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QStyle, QVBoxLayout, QWidget,
)

from config import BASE_LOG_DIRECTORY

try:
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineSettings = None
    QWebEngineView = None

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:
    QPdfDocument = None
    QPdfView = None


class HeightForWidthWidget(QWidget):
    """Propagate wrapped child height through nested layouts."""

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        widget_layout = self.layout()
        if widget_layout is None:
            return super().heightForWidth(width)
        return widget_layout.totalHeightForWidth(width)


class AutoHeightLabel(QLabel):
    """Keep a wrapped rich-text label exactly tall enough for all its text."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        required_height = self.heightForWidth(event.size().width())
        if required_height > 0 and self.height() != required_height:
            self.setFixedHeight(required_height)
            self.updateGeometry()


PROJECT_OVERVIEW_HTML = """
<div style="color: #292929;">
  <p style="text-align: justify;">
    <b>Rising Sun No. 1 (红太阳一号)</b> is a self-developed unmanned aerial
    vehicle (UAV) project. Its primary objective is to create a complete and
    integrated flight system including a drone that performs flight missions,
    a ground control station that monitors and visualizes flight status, and an
    onboard computer that manages high-level flight tasks. The main goal of
    this project is to successfully develop each subsystem and integrate them
    into a coordinated and functional system. Through this process, the project
    can improved systems-thinking and problem-solving abilities while also
    developing the specialized engineering skills required to design, build,
    and test each subsystem.
  </p>
</div>
"""

DRONE_DESCRIPTION_HTML = """
<div style="color: #292929;">
  <h2 style="margin-bottom: 8px;">01&nbsp;&nbsp;Drone Subsystem</h2>
  <p>
    The drone provides a stable, controllable, and flyable aerial platform by
    integrating electrical, propulsion, and flight-control systems.
  </p>
  <p>
    <b>Electrical system.</b> A 4S LiPo battery powers the aircraft. The power
    module supplies and monitors the flight controller, while the power
    distribution board (PDB) distributes power to the propulsion, onboard
    computer, and video transmission (VTX) systems.
  </p>
  <p>
    <b>Propulsion system.</b> Four Tarot 2814 700 KV motors with 12 × 3.8-inch
    propellers are driven by four Talon 40A Slim ESCs running AM32 firmware.
    The system can theoretically produce 7,200 g of total thrust—approximately
    twice the aircraft's weight—with a maximum current draw of 100 A and a
    hovering current of about 25 A.
  </p>
  <p>
    <b>Flight-control system.</b> A Pixhawk 6C Pro flight controller and an M10
    GPS module provide flight stabilization, navigation, and aircraft-state
    estimation. Mission Planner 1.3.83 is used to configure the controller,
    calibrate its sensors and radio inputs, adjust flight parameters, and
    monitor the aircraft during testing.
  </p>
</div>
"""

GROUND_STATION_DESCRIPTION_HTML = """
<div style="color: #292929;">
  <h2 style="margin-bottom: 8px;">02&nbsp;&nbsp;Ground Control Station</h2>
  <p>
    A custom ground control station was developed so the complete system could
    be designed around the project's own requirements rather than relying on
    Mission Planner as the primary flight interface. It combines the live VTX
    video feed with visualized telemetry, helping the pilot assess aircraft
    status and make decisions intuitively. It also records, organizes, and
    visualizes flight logs for post-flight analysis.
  </p>
  <p>
    The Flight Display is inspired by commercial-aircraft cockpit displays. It
    includes a head-up display (HUD), a GPS-based map, flight instruments, and
    Information Panels that present system status, operating information, and
    active warnings. Future versions may also support waypoint and high-level
    flight-task entry directly through the interface.
  </p>
</div>
"""

ONBOARD_COMPUTER_DESCRIPTION_HTML = """
<div style="color: #292929;">
  <h2 style="margin-bottom: 8px;">03&nbsp;&nbsp;Onboard Computer</h2>
  <p>
    A Raspberry Pi 4 provides the high-level computing layer. The Pixhawk
    handles real-time attitude stabilization and motion control, while the
    Raspberry Pi manages system coordination, data processing, communication,
    and higher-level tasks. This layered architecture provides a foundation
    for autonomous navigation, computer vision, obstacle avoidance, and
    advanced mission planning.
  </p>
  <p>
    The Raspberry Pi monitors the aircraft through a three-stage finite-state
    machine: <b>Before Takeoff</b>, <b>Cruising</b>, and <b>After Landing</b>.
    It controls the navigation, strobe, and beacon lights; performs and reports
    the preflight checklist through MAVLink; records flight data; and transfers
    the completed CSV log to the corresponding ground-station folder via
    Bluetooth after landing.
  </p>
</div>
"""

FUTURE_AIRCRAFT_IMPROVEMENTS_HTML = """
<div style="color: #292929;">
  <p style="text-align: justify;">
    In the future, several aspects of the aircraft can be improved. First, the
    entire power system could be redesigned around a 6S battery. This would
    allow the use of lower-KV motors with greater torque, enabling the drone to
    carry heavier payloads. The current ESCs could also be replaced with models
    that use plug-in connectors, reducing the number of solder joints and
    making assembly, maintenance, and component replacement easier. The current
    Pixhawk flight controller could also be replaced with a smaller bare-board
    flight controller. This would provide more hardware options while reducing
    the aircraft's size and weight, resulting in a design closer to modern
    commercial drones. However, a bare-board controller would require more
    soldering and a more complicated wiring process.
  </p>
</div>
"""

FUTURE_PROJECT_DEVELOPMENT_HTML = """
<div style="color: #292929;">
  <p style="text-align: justify;">
    This project has established a functional and flyable aerial platform,
    providing a foundation for further development. Future work can proceed in
    two main directions. First, a preliminary flight-control program could be
    independently developed to explore the fundamental principles of robot
    dynamics, flight stabilization, and motion control. Second, the Raspberry
    Pi's high-level task-management system could be extended to perform more
    complex autonomous tasks, such as obstacle detection and avoidance using
    trained machine-learning models.
  </p>
</div>
"""


# Local PDF certificates stored in 红太阳App/assets.
CERTIFICATE_FILES = (
    ("Pilot Certificate Basic", "Pilot Certificate Basic.pdf"),
    ("Aircraft Registration", "Registration.pdf"),
)


class HomePage(QWidget):
    """Home page with a fixed-size, scrollable flight-log browser."""

    open_dashboard = Signal()
    open_log = Signal(str)

    def __init__(self):
        super().__init__()
        self.current_log_folder = None
        # Keep non-modal full-certificate windows alive until the user closes
        # them. Without a retained reference, Python can destroy the window.
        self._certificate_windows = []

        title = QLabel("Rising Sun No. 1 (红太阳一号)")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "QLabel { color: #181818; font-size: 44px; font-weight: 700; }"
        )

        overview_title = QLabel("Project Overview")
        overview_title.setAlignment(Qt.AlignCenter)
        overview_title.setStyleSheet(
            "QLabel { color: #202020; font-size: 25px; font-weight: 650; }"
        )
        overview = self._make_rich_text(PROJECT_OVERVIEW_HTML)
        overview.setAlignment(Qt.AlignTop | Qt.AlignJustify)
        overview.setMinimumHeight(150)

        overview_panel = QFrame()
        overview_panel.setObjectName("overviewPanel")
        overview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        overview_panel.setStyleSheet(
            "QFrame#overviewPanel {"
            "  background: transparent; border: 2px solid #b31313;"
            "  border-radius: 8px;"
            "}"
        )
        overview_layout = QVBoxLayout(overview_panel)
        overview_layout.setContentsMargins(28, 18, 28, 20)
        overview_layout.setSpacing(8)
        overview_layout.addWidget(overview_title)
        overview_layout.addWidget(overview)

        model_panel = self._make_model_viewer()

        enter_button = QPushButton("Enter Flight Display")
        enter_button.setFixedSize(220, 50)
        enter_button.clicked.connect(self.open_dashboard.emit)
        enter_button.setStyleSheet(
            "QPushButton {"
            "  color: white; background: #b31313; border: none;"
            "  border-radius: 6px; font-size: 14px; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #cf1b1b; }"
            "QPushButton:pressed { background: #8f0d0d; }"
        )

        drone_section = self._make_section(DRONE_DESCRIPTION_HTML)
        product_list_link = self._make_asset_file_link(
            "Whole Product View List",
            "Drone FDCR (1).xlsx",
        )
        electrical_wiring_link = self._make_asset_file_link(
            "Electrical Wiring",
            "Electrical Wiring.drawio.png",
        )

        # Keep the spreadsheet link directly below Section 01 in the empty
        # left-column space, rather than placing it with the page-wide logs.
        drone_column = HeightForWidthWidget()
        drone_column.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        drone_column_layout = QVBoxLayout(drone_column)
        drone_column_layout.setContentsMargins(0, 0, 0, 0)
        drone_column_layout.setSpacing(12)
        drone_column_layout.addWidget(drone_section)
        drone_column_layout.addWidget(
            product_list_link,
            alignment=Qt.AlignLeft,
        )
        drone_column_layout.addWidget(
            electrical_wiring_link,
            alignment=Qt.AlignLeft,
        )
        ground_section = self._make_section(GROUND_STATION_DESCRIPTION_HTML)
        onboard_section = self._make_section(ONBOARD_COMPUTER_DESCRIPTION_HTML)

        right_sections = HeightForWidthWidget()
        right_sections.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        right_layout = QVBoxLayout(right_sections)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(18)
        right_layout.addWidget(ground_section)
        right_layout.addWidget(onboard_section)

        systems_layout = QHBoxLayout()
        systems_layout.setContentsMargins(0, 0, 0, 0)
        systems_layout.setSpacing(42)
        systems_layout.addWidget(drone_column, 1, alignment=Qt.AlignTop)
        systems_layout.addWidget(right_sections, 1, alignment=Qt.AlignTop)

        improvements_panel = QFrame()
        improvements_panel.setObjectName("improvementsPanel")
        improvements_panel.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        improvements_panel.setStyleSheet(
            "QFrame#improvementsPanel {"
            "  background: transparent; border: 2px solid #b31313;"
            "  border-radius: 8px;"
            "}"
        )
        improvements_layout = QVBoxLayout(improvements_panel)
        improvements_layout.setContentsMargins(28, 16, 28, 18)
        improvements_layout.setSpacing(8)

        improvements_title = QLabel("Future Aircraft Improvements")
        improvements_title.setAlignment(Qt.AlignCenter)
        improvements_title.setStyleSheet(
            "QLabel { color: #202020; font-size: 25px; font-weight: 650; }"
        )
        improvements_layout.addWidget(improvements_title)
        improvements_layout.addWidget(
            self._make_rich_text(FUTURE_AIRCRAFT_IMPROVEMENTS_HTML)
        )

        development_panel = QFrame()
        development_panel.setObjectName("developmentPanel")
        development_panel.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        development_panel.setStyleSheet(
            "QFrame#developmentPanel {"
            "  background: transparent; border: 2px solid #b31313;"
            "  border-radius: 8px;"
            "}"
        )
        development_layout = QVBoxLayout(development_panel)
        development_layout.setContentsMargins(28, 16, 28, 18)
        development_layout.setSpacing(8)

        development_title = QLabel("Future Project Development")
        development_title.setAlignment(Qt.AlignCenter)
        development_title.setStyleSheet(
            "QLabel { color: #202020; font-size: 25px; font-weight: 650; }"
        )
        development_layout.addWidget(development_title)
        development_layout.addWidget(
            self._make_rich_text(FUTURE_PROJECT_DEVELOPMENT_HTML)
        )

        self.logs_title = QLabel("Flight Logs")
        self.logs_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.folder_back_button = QPushButton("← Flight folders")
        self.folder_back_button.clicked.connect(self._show_flight_folders)
        self.folder_back_button.hide()
        refresh_button = QPushButton("Refresh")
        refresh_button.setFixedWidth(90)
        refresh_button.clicked.connect(self.refresh_logs)

        logs_header = QHBoxLayout()
        logs_header.setContentsMargins(0, 0, 0, 0)
        logs_header.addWidget(self.folder_back_button)
        logs_header.addWidget(self.logs_title)
        logs_header.addStretch()
        logs_header.addWidget(refresh_button)

        self.log_list = QListWidget()
        self.log_list.setFixedHeight(230)
        self.log_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.log_list.setAlternatingRowColors(True)
        self.log_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.log_list.setToolTip(
            "Click a flight folder to view its files; click a CSV to open Log Viewer"
        )
        self.log_list.itemClicked.connect(self._activate_log_item)

        logs_panel = QWidget()
        logs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        logs_layout = QVBoxLayout(logs_panel)
        logs_layout.setContentsMargins(0, 8, 0, 10)
        logs_layout.setSpacing(8)
        logs_layout.addLayout(logs_header)
        logs_layout.addWidget(self.log_list)

        certificates_panel = self._make_certificates_panel()

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("QFrame { color: #d3d3d3; }")

        body = QWidget()
        body.setMaximumWidth(1320)
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(22)
        body_layout.addWidget(title)
        body_layout.addSpacing(8)
        body_layout.addWidget(model_panel)
        body_layout.addSpacing(8)
        body_layout.addWidget(overview_panel)
        body_layout.addSpacing(24)
        body_layout.addLayout(systems_layout)
        body_layout.addSpacing(24)
        body_layout.addWidget(improvements_panel)
        body_layout.addSpacing(24)
        body_layout.addWidget(development_panel)
        body_layout.addSpacing(24)
        body_layout.addWidget(enter_button, alignment=Qt.AlignCenter)
        body_layout.addSpacing(18)
        body_layout.addWidget(separator)
        body_layout.addWidget(logs_panel)
        body_layout.addSpacing(22)
        body_layout.addWidget(certificates_panel)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(46, 46, 46, 60)
        content_layout.addWidget(body, alignment=Qt.AlignTop | Qt.AlignHCenter)
        content_layout.addStretch()

        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QScrollArea.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page_scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(page_scroll)
        self.refresh_logs()

    def _make_certificates_panel(self):
        """Create two embedded certificate previews at the page bottom."""
        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        title = QLabel("Certificates")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "QLabel { color: #202020; font-size: 25px; font-weight: 650; }"
        )

        cards_layout = QHBoxLayout()
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(24)

        assets_directory = self._project_root() / "assets"
        for certificate_title, certificate_filename in CERTIFICATE_FILES:
            cards_layout.addWidget(
                self._make_certificate_card(
                    certificate_title,
                    assets_directory / certificate_filename,
                ),
                1,
            )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 10)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addLayout(cards_layout)
        return panel

    def _make_certificate_card(self, title, certificate_path):
        """Embed the first page of one local PDF certificate."""
        certificate_path = Path(certificate_path).resolve()
        card = QFrame()
        card.setObjectName("certificateCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setFixedHeight(430)
        card.setStyleSheet(
            "QFrame#certificateCard {"
            "  background: #ffffff; border: 1px solid #d5d5d5;"
            "  border-radius: 8px;"
            "}"
        )

        heading = QLabel(title)
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet(
            "QLabel { color: #202020; font-size: 17px; font-weight: 650; }"
        )

        open_button = QPushButton("Open Full Certificate")
        open_button.setFixedHeight(36)
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.clicked.connect(
            lambda checked=False, path=certificate_path:
            self._open_full_certificate(title, path)
        )
        open_button.setStyleSheet(
            "QPushButton {"
            "  color: white; background: #b31313; border: none;"
            "  border-radius: 5px; font-size: 13px; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #cf1b1b; }"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 12, 10, 10)
        card_layout.setSpacing(10)
        card_layout.addWidget(heading)

        if not certificate_path.is_file():
            preview = QLabel(
                "PDF certificate not found:\n"
                f"{certificate_path.name}\n\n"
                "Place this file in 红太阳App/assets."
            )
            preview.setAlignment(Qt.AlignCenter)
            preview.setWordWrap(True)
            preview.setStyleSheet(
                "QLabel { background: #f6f6f6; color: #b31313; border: none; }"
            )
            open_button.setEnabled(False)
            card_layout.addWidget(preview, 1)
        elif QPdfDocument is not None and QPdfView is not None:
            document = QPdfDocument(card)
            document.load(str(certificate_path))

            preview = QPdfView()
            preview.setDocument(document)
            preview.setPageMode(QPdfView.PageMode.SinglePage)
            preview.setZoomMode(QPdfView.ZoomMode.FitInView)
            preview.setStyleSheet(
                "QPdfView { background: #eeeeee; border: none; }"
            )
            card_layout.addWidget(preview, 1)
        elif QWebEngineView is None:
            preview = QLabel(
                "Certificate preview requires PySide6 PDF or WebEngine.\n"
                "Install it with:  pip install PySide6-Addons"
            )
            preview.setAlignment(Qt.AlignCenter)
            preview.setWordWrap(True)
            preview.setStyleSheet(
                "QLabel { background: #f6f6f6; color: #666; border: none; }"
            )
            card_layout.addWidget(preview, 1)
        else:
            preview = QWebEngineView()
            preview.setContextMenuPolicy(Qt.NoContextMenu)
            preview.settings().setAttribute(
                QWebEngineSettings.WebAttribute.PluginsEnabled,
                True,
            )
            preview.setUrl(QUrl.fromLocalFile(str(certificate_path)))
            card_layout.addWidget(preview, 1)

        card_layout.addWidget(open_button)
        return card

    def _open_full_certificate(self, title, certificate_path):
        """Open a full PDF window above the main application window."""
        certificate_path = Path(certificate_path).resolve()
        if not certificate_path.is_file():
            QMessageBox.warning(
                self,
                "Certificate Not Found",
                f"No PDF certificate was found at:\n{certificate_path}",
            )
            return

        # Use an in-app PDF window when Qt PDF is available. It is a separate
        # top-level window, stays above MainWindow, and is explicitly raised.
        if QPdfDocument is not None and QPdfView is not None:
            dialog = QDialog(self)
            dialog.setWindowTitle(title)
            dialog.setWindowFlags(
                Qt.Window
                | Qt.WindowTitleHint
                | Qt.WindowMinMaxButtonsHint
                | Qt.WindowCloseButtonHint
                | Qt.WindowStaysOnTopHint
            )
            dialog.resize(1000, 820)
            dialog.setMinimumSize(700, 560)

            document = QPdfDocument(dialog)
            document.load(str(certificate_path))

            pdf_view = QPdfView(dialog)
            pdf_view.setDocument(document)
            pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)

            close_button = QPushButton("Close")
            close_button.setFixedSize(110, 36)
            close_button.clicked.connect(dialog.close)

            dialog_layout = QVBoxLayout(dialog)
            dialog_layout.setContentsMargins(10, 10, 10, 10)
            dialog_layout.setSpacing(8)
            dialog_layout.addWidget(pdf_view, 1)
            dialog_layout.addWidget(close_button, alignment=Qt.AlignRight)

            self._certificate_windows.append(dialog)
            dialog.finished.connect(
                lambda result=0, window=dialog:
                self._forget_certificate_window(window)
            )
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return

        # Fallback for an installation without Qt PDF. Windows may control the
        # foreground behavior of its external PDF reader.
        if not QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(certificate_path))
        ):
            QMessageBox.warning(
                self,
                "Unable to Open Certificate",
                f"No application could open:\n{certificate_path}",
            )

    def _forget_certificate_window(self, window):
        if window in self._certificate_windows:
            self._certificate_windows.remove(window)

    @staticmethod
    def _project_root():
        """Locate 红太阳App independently of the working directory."""
        source_path = Path(__file__).resolve()
        project_root = next(
            (parent for parent in source_path.parents if parent.name == "红太阳App"),
            None,
        )
        if project_root is not None:
            return project_root

        cwd_project = Path.cwd() / "红太阳App"
        return cwd_project if cwd_project.is_dir() else source_path.parent

    def _make_model_viewer(self):
        """Create an interactive viewer for the first GLB in ./assets."""
        panel = QFrame()
        panel.setObjectName("modelPanel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        panel.setFixedHeight(560)
        panel.setStyleSheet(
            "QFrame#modelPanel {"
            "  background: #f4f4f4; border: 1px solid #d5d5d5;"
            "  border-radius: 8px;"
            "}"
        )

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(1, 1, 1, 1)

        # The model belongs to the project-level 红太阳App/assets directory.
        # Locate that project folder without depending on the process working
        # directory or on where this module is imported from.
        project_root = self._project_root()
        assets_directory = project_root / "assets"
        glb_files = sorted(assets_directory.glob("*.glb"))

        if QWebEngineView is None:
            message = QLabel(
                "3D viewer requires PySide6 WebEngine.\n"
                "Install it with:  pip install PySide6-Addons"
            )
            message.setAlignment(Qt.AlignCenter)
            message.setStyleSheet("color: #666; font-size: 15px;")
            panel_layout.addWidget(message)
            return panel

        if not glb_files:
            message = QLabel(
                "No GLB model found.\n"
                f"Place the model in: {assets_directory}"
            )
            message.setAlignment(Qt.AlignCenter)
            message.setWordWrap(True)
            message.setStyleSheet("color: #666; font-size: 15px;")
            panel_layout.addWidget(message)
            return panel

        model_path = glb_files[0]
        model_name = escape(model_path.name, quote=True)

        viewer = QWebEngineView()
        viewer.setContextMenuPolicy(Qt.NoContextMenu)
        settings = viewer.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )

        viewer_html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script type="module"
          src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.1.0/model-viewer.min.js">
  </script>
  <style>
    html, body {{ width: 100%; height: 100%; margin: 0; overflow: hidden; }}
    body {{ background: #f4f4f4; }}
    model-viewer {{ width: 100%; height: 100%; --poster-color: #f4f4f4; }}
    .hint {{
      position: absolute; right: 18px; bottom: 14px; z-index: 2;
      padding: 7px 11px; border-radius: 5px;
      color: #555; background: rgba(255,255,255,.82);
      font: 12px Arial, sans-serif; pointer-events: none;
    }}
  </style>
</head>
<body>
  <model-viewer
      src="{model_name}"
      alt="Red Sun No. 1 drone 3D model"
      camera-controls
      auto-rotate
      auto-rotate-delay="1500"
      rotation-per-second="10deg"
      shadow-intensity="1"
      shadow-softness="0.8"
      exposure="1"
      environment-image="neutral"
      interaction-prompt="auto">
  </model-viewer>
  <div class="hint">Drag to rotate · Scroll to zoom</div>
</body>
</html>"""

        viewer.setHtml(
            viewer_html,
            QUrl.fromLocalFile(str(assets_directory.resolve()) + "/"),
        )
        panel_layout.addWidget(viewer)
        return panel

    @staticmethod
    def _make_rich_text(html, auto_height=False):
        label = AutoHeightLabel(html) if auto_height else QLabel(html)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label.setStyleSheet(
            "QLabel {"
            "  color: #292929; background: transparent; border: none;"
            "  padding: 0; font-size: 15px;"
            "}"
        )
        return label

    @classmethod
    def _make_section(cls, html):
        section = HeightForWidthWidget()
        section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QHBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        accent = QFrame()
        accent.setFixedWidth(4)
        accent.setStyleSheet("QFrame { background: #b31313; border-radius: 2px; }")
        layout.addWidget(accent)
        layout.addWidget(cls._make_rich_text(html, auto_height=True), 1)
        return section

    def _make_asset_file_link(self, text, filename):
        """Create a link-style button that opens one file from ./assets."""
        file_path = (self._project_root() / "assets" / filename).resolve()

        button = QPushButton(f"↗  {text}")
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setToolTip(str(file_path))
        button.setStyleSheet(
            "QPushButton {"
            "  color: #b31313; background: transparent; border: none;"
            "  padding: 5px 8px; font-size: 15px; font-weight: 650;"
            "  text-align: left; text-decoration: underline;"
            "}"
            "QPushButton:hover { color: #d21d1d; background: #f7eaea; }"
            "QPushButton:pressed { color: #850b0b; }"
        )
        button.clicked.connect(
            lambda checked=False, path=file_path:
            self._open_asset_file(path)
        )
        return button

    def _open_asset_file(self, file_path):
        """Open an assets file in its Windows-associated application."""
        file_path = Path(file_path).resolve()
        if not file_path.is_file():
            QMessageBox.warning(
                self,
                "File Not Found",
                f"The product list was not found at:\n{file_path}",
            )
            return

        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path))):
            QMessageBox.warning(
                self,
                "Unable to Open File",
                f"No application could open:\n{file_path}",
            )

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_logs()

    def refresh_logs(self):
        self.log_list.clear()
        log_root = Path(BASE_LOG_DIRECTORY).resolve()
        log_root.mkdir(parents=True, exist_ok=True)

        if self.current_log_folder is not None:
            folder = Path(self.current_log_folder)
            if folder.is_dir() and folder.parent == log_root:
                self._populate_folder_files(folder)
                return
            self.current_log_folder = None

        self._populate_flight_folders(log_root)

    def _populate_flight_folders(self, log_root):
        self.folder_back_button.hide()
        self.logs_title.setText("Flight Logs")
        try:
            flight_folders = sorted(
                (path for path in log_root.iterdir() if path.is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            flight_folders = []

        if not flight_folders:
            item = QListWidgetItem("No flight folders found")
            item.setFlags(Qt.NoItemFlags)
            self.log_list.addItem(item)
            return

        folder_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        for folder in flight_folders:
            item = QListWidgetItem(folder_icon, folder.name)
            item.setData(Qt.UserRole, str(folder))
            item.setData(Qt.UserRole + 1, "folder")
            item.setToolTip(str(folder))
            self.log_list.addItem(item)

    def _populate_folder_files(self, folder):
        self.current_log_folder = folder
        self.folder_back_button.show()
        self.logs_title.setText(folder.name)
        try:
            files = sorted(
                (path for path in folder.iterdir() if path.is_file()),
                key=lambda path: (path.suffix.lower(), path.name.lower()),
            )
        except OSError as error:
            files = []
            QMessageBox.warning(self, "Unable to Read Flight Folder", str(error))

        if not files:
            item = QListWidgetItem("This flight folder is empty")
            item.setFlags(Qt.NoItemFlags)
            self.log_list.addItem(item)
            return

        file_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        for path in files:
            item = QListWidgetItem(file_icon, path.name)
            item.setData(Qt.UserRole, str(path))
            item.setData(Qt.UserRole + 1, "file")
            item.setToolTip(str(path))
            self.log_list.addItem(item)

    def _show_flight_folders(self):
        self.current_log_folder = None
        self.refresh_logs()

    def _activate_log_item(self, item):
        path_text = item.data(Qt.UserRole)
        item_type = item.data(Qt.UserRole + 1)
        if not path_text:
            return

        path = Path(path_text)
        if item_type == "folder":
            self.log_list.clear()
            self._populate_folder_files(path)
        elif path.suffix.lower() == ".csv":
            self.open_log.emit(str(path))
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(
                self,
                "Unable to Open File",
                f"No application could open this file:\n{path}",
            )