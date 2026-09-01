import sys
import threading
import os
import json

from pathlib import Path
from functools import partial
from http.server import (
    ThreadingHTTPServer,
    SimpleHTTPRequestHandler,
)

from PySide6.QtCore import QUrl

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
)

from PySide6.QtWebEngineWidgets import (
    QWebEngineView,
)


# =========================
# Local map server
# =========================

HOST = "127.0.0.1"
PORT = 8765


# =========================
# HTTP handler with
# Range Request support
# =========================

class RangeRequestHandler(
    SimpleHTTPRequestHandler
):

    def send_head(self):

        path = self.translate_path(
            self.path
        )

        # =========================
        # Directory handling
        # =========================

        if os.path.isdir(path):

            return super().send_head()


        # =========================
        # File not found
        # =========================

        if not os.path.exists(path):

            self.send_error(
                404,
                "File not found",
            )

            return None


        try:

            file_object = open(
                path,
                "rb",
            )

        except OSError:

            self.send_error(
                404,
                "File not found",
            )

            return None


        file_size = os.path.getsize(
            path
        )


        # =========================
        # Check Range header
        # =========================

        range_header = self.headers.get(
            "Range"
        )


        # =========================
        # Normal full-file request
        # =========================

        if not range_header:

            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                self.guess_type(path),
            )

            self.send_header(
                "Content-Length",
                str(file_size),
            )

            self.send_header(
                "Accept-Ranges",
                "bytes",
            )

            self.end_headers()

            return file_object


        # =========================
        # Range request
        #
        # Example:
        # bytes=0-16383
        # =========================

        try:

            units, range_value = (
                range_header.split(
                    "=",
                    1,
                )
            )

            if units != "bytes":

                raise ValueError


            start_text, end_text = (
                range_value.split(
                    "-",
                    1,
                )
            )


            if start_text:

                start = int(
                    start_text
                )

            else:

                start = 0


            if end_text:

                end = int(
                    end_text
                )

            else:

                end = (
                    file_size - 1
                )


            end = min(
                end,
                file_size - 1,
            )


            if (
                start < 0
                or
                start >= file_size
                or
                end < start
            ):

                raise ValueError


        except ValueError:

            file_object.close()

            self.send_error(
                416,
                "Requested Range Not Satisfiable",
            )

            return None


        # =========================
        # Partial Content
        # =========================

        content_length = (
            end
            - start
            + 1
        )


        self.send_response(
            206
        )

        self.send_header(
            "Content-Type",
            self.guess_type(path),
        )

        self.send_header(
            "Content-Range",
            f"bytes {start}-{end}/{file_size}",
        )

        self.send_header(
            "Content-Length",
            str(content_length),
        )

        self.send_header(
            "Accept-Ranges",
            "bytes",
        )

        self.end_headers()


        # Remember requested range
        self.range_start = start
        self.range_end = end


        file_object.seek(
            start
        )

        return file_object


    # =========================
    # Copy only requested bytes
    # =========================

    def copyfile(
        self,
        source,
        outputfile,
    ):

        if (
            hasattr(
                self,
                "range_start",
            )
            and
            hasattr(
                self,
                "range_end",
            )
        ):

            remaining = (
                self.range_end
                - self.range_start
                + 1
            )


            buffer_size = (
                64 * 1024
            )


            while remaining > 0:

                chunk = source.read(
                    min(
                        buffer_size,
                        remaining,
                    )
                )

                if not chunk:

                    break


                outputfile.write(
                    chunk
                )


                remaining -= len(
                    chunk
                )


            del self.range_start
            del self.range_end


        else:

            super().copyfile(
                source,
                outputfile,
            )


# =========================
# Map Widget
# =========================

class MapWidget(QWidget):

    def __init__(self):

        super().__init__()


        # =========================
        # Map directory
        # =========================

        self.map_directory = (
            Path(__file__)
            .resolve()
            .parent
        )


        # =========================
        # Local map server
        # =========================

        self.http_server = None
        self.server_thread = None

        self.start_local_server()


        # =========================
        # Current flight state
        # =========================

        self.gps_valid = False

        self.latitude = None
        self.longitude = None

        self.heading = 0.0

        self.armed = False

        # Used to detect:
        #
        # DISARMED -> ARMED
        self.previous_armed = False


        # =========================
        # Home / pilot position
        # =========================


        # =========================
        # Web page state
        # =========================

        self.page_loaded = False


        # =========================
        # Web view
        # =========================

        self.web_view = (
            QWebEngineView()
        )


        # Detect map.html ready
        self.web_view.loadFinished.connect(
            self.on_page_loaded
        )


        # =========================
        # Layout
        # =========================

        layout = QVBoxLayout()

        layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        layout.setSpacing(
            0
        )

        layout.addWidget(
            self.web_view
        )

        self.setLayout(
            layout
        )


        # =========================
        # Open map
        # =========================

        self.web_view.setUrl(
            QUrl(
                f"http://{HOST}:{PORT}/map.html"
            )
        )


    # =========================
    # Page loaded
    # =========================

    def on_page_loaded(
        self,
        success,
    ):

        self.page_loaded = bool(
            success
        )


        print(
            "Map page loaded:",
            success
        )


        if not success:

            return


        # Send current state immediately
        # after map.html finishes loading.
        self.sync_map_state()


    # =========================
    # Run JavaScript safely
    # =========================

    def run_javascript(
        self,
        javascript,
    ):

        if not self.page_loaded:

            return


        self.web_view.page().runJavaScript(
            javascript
        )


    # =========================
    # GPS valid / invalid
    # =========================

    def set_gps_valid(
        self,
        valid,
    ):

        self.gps_valid = bool(
            valid
        )


        javascript = (
            "if (window.setGpsValid) {"
            f"window.setGpsValid({str(self.gps_valid).lower()});"
            "}"
        )


        self.run_javascript(
            javascript
        )


    # =========================
    # Aircraft position
    # =========================

    def set_aircraft_position(
        self,
        latitude,
        longitude,
        heading,
        record_track=False,
    ):

        if (
            latitude is None
            or longitude is None
        ):

            return


        try:

            latitude = float(
                latitude
            )

            longitude = float(
                longitude
            )

            heading = float(
                heading
                if heading is not None
                else 0.0
            )

        except (
            TypeError,
            ValueError,
        ):

            return


        self.latitude = latitude
        self.longitude = longitude
        self.heading = heading


        # Normalize heading:
        #
        # 0   = North
        # 90  = East
        # 180 = South
        # 270 = West
        self.heading %= 360.0


        javascript = (
            "if (window.updateAircraft) {"
            "window.updateAircraft("
            f"{json.dumps(self.latitude)},"
            f"{json.dumps(self.longitude)},"
            f"{json.dumps(self.heading)},"
            f"{str(bool(record_track)).lower()}"
            ");"
            "}"
        )


        self.run_javascript(
            javascript
        )


    # =========================
    # ARM state
    # =========================

    def set_armed(
        self,
        armed,
    ):

        armed = bool(
            armed
        )


        # =========================
        # DISARMED -> ARMED
        #
        # Start a new flight:
        # clear previous track.
        # =========================

        if (
            armed
            and
            not self.previous_armed
        ):

            print(
                "Map: ARMED - starting new track."
            )


            self.run_javascript(
                """
                if (window.clearFlightTrack) {
                    window.clearFlightTrack();
                }
                """
            )


        # =========================
        # ARMED -> DISARMED
        #
        # Stop recording, but keep
        # the existing track visible.
        # =========================

        if (
            not armed
            and
            self.previous_armed
        ):

            print(
                "Map: DISARMED - track recording stopped."
            )


        self.armed = armed

        self.previous_armed = (
            armed
        )


        # Tell map.html current ARM state
        javascript = (
            "if (window.setArmed) {"
            f"window.setArmed({str(self.armed).lower()});"
            "}"
        )

        self.run_javascript(
            javascript
        )

    # =========================
    # Main telemetry input
    # =========================

    def update_flight_state(
        self,
        gps_valid,
        latitude,
        longitude,
        heading,
        armed,
    ):

        # =========================
        # GPS state
        # =========================

        self.set_gps_valid(
            gps_valid
        )


        # =========================
        # Update stored position
        # =========================

        if (
            latitude is not None
            and
            longitude is not None
        ):

            try:

                self.latitude = float(
                    latitude
                )

                self.longitude = float(
                    longitude
                )

            except (
                TypeError,
                ValueError,
            ):

                pass


        if heading is not None:

            try:

                self.heading = (
                    float(heading)
                    % 360.0
                )

            except (
                TypeError,
                ValueError,
            ):

                pass


        # =========================
        # ARM transition
        #
        # Do this AFTER storing
        # latest GPS position.
        # =========================

        self.set_armed(
            armed
        )


        # =========================
        # Aircraft marker
        # =========================

        if (
            self.gps_valid
            and
            self.latitude is not None
            and
            self.longitude is not None
        ):

            # Track only while armed.
            record_track = (
                self.armed
            )


            self.set_aircraft_position(
                self.latitude,
                self.longitude,
                self.heading,
                record_track=record_track,
            )


    # =========================
    # Synchronize current state
    # after map loads
    # =========================

    def sync_map_state(self):

        self.set_gps_valid(
            self.gps_valid
        )


        if (
            self.gps_valid
            and
            self.latitude is not None
            and
            self.longitude is not None
        ):

            self.set_aircraft_position(
                self.latitude,
                self.longitude,
                self.heading,
                record_track=False,
            )


        javascript = (
            "if (window.setArmed) {"
            f"window.setArmed({str(self.armed).lower()});"
            "}"
        )

        self.run_javascript(
            javascript
        )


    # =========================
    # Clear track manually
    # =========================

    def clear_flight_track(self):

        self.run_javascript(
            """
            if (window.clearFlightTrack) {
                window.clearFlightTrack();
            }
            """
        )


    # =========================
    # Start local server
    # =========================

    def start_local_server(self):

        handler = partial(
            RangeRequestHandler,
            directory=str(
                self.map_directory
            ),
        )


        try:

            self.http_server = (
                ThreadingHTTPServer(
                    (
                        HOST,
                        PORT,
                    ),
                    handler,
                )
            )


        except OSError:

            print(
                "Map server already running:"
                f" http://{HOST}:{PORT}"
            )

            return


        self.server_thread = (
            threading.Thread(
                target=(
                    self.http_server
                    .serve_forever
                ),
                daemon=True,
            )
        )


        self.server_thread.start()


        print(
            "Map server started:"
            f" http://{HOST}:{PORT}"
        )


    # =========================
    # Stop local server
    # =========================

    def stop_local_server(self):

        if self.http_server is None:

            return


        self.http_server.shutdown()

        self.http_server.server_close()

        self.http_server = None


# =========================
# Standalone test
# =========================

if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )


    window = MapWidget()

    window.resize(
        1200,
        800,
    )

    window.show()


    exit_code = app.exec()


    window.stop_local_server()


    sys.exit(
        exit_code
    )