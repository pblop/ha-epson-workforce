"""Epson WorkForce API."""

from __future__ import annotations

import ssl
from typing import Any
import urllib.error
import urllib.request

from .parser import EpsonHTMLParser, EpsonMaintenanceHTMLParser


def _get_html_from_url(context, url: str, timeout: float = 5.0) -> str:
    req = urllib.request.Request(url)
    req.add_header("Cookie", "EPSON_COOKIE_LANG=lang_b&1/lang_a&1")
    with urllib.request.urlopen(req, context=context, timeout=timeout) as response:
        data_bytes = response.read()
    return data_bytes.decode("utf-8", errors="ignore")


class EpsonWorkForceAPI:
    def __init__(
        self,
        ip: str,
        main_path: str,
        maintenance_path: str = None,
        timeout: float = 5.0,
    ):
        self._main_resource = "http://" + ip + main_path
        self._maintenance_resource = (
            "http://" + ip + maintenance_path if maintenance_path else None
        )
        self._ip = ip  # Store IP address for diagnostic sensor
        self.available: bool = True
        self._timeout = timeout

        # Internal
        self._main_parser: EpsonHTMLParser | None = None
        self._maintenance_parser: EpsonMaintenanceHTMLParser | None = None
        self._data: dict[str, Any] | None = None  # parsed dict cache

        # Defaults
        self._model: str | None = None
        self._mac: str | None = None

        self.update()

    @property
    def name(self) -> str | None:
        """Returns the name of the printer."""
        self._ensure_parsed()
        return (self._data or {}).get("name")

    @property
    def model(self) -> str:
        """Returns the model name of the printer."""
        self._ensure_parsed()
        return (self._data or {}).get("model") or "WorkForce Printer"

    @property
    def mac_address(self) -> str | None:
        """Returns the MAC address of the device if available."""
        self._ensure_parsed()
        return (self._data or {}).get("mac_address")

    def update(self) -> None:
        """
        Fetch and parse the HTML page from the device (rebuilds parser + resets cache).
        """
        try:
            context = ssl._create_unverified_context()

            html_text = _get_html_from_url(context, self._main_resource, self._timeout)
            self._main_parser = EpsonHTMLParser(html_text, source=self._main_resource)

            if self._maintenance_resource is not None:
                maintenance_html_text = _get_html_from_url(
                    context,
                    self._maintenance_resource,
                    self._timeout,
                )
                self._maintenance_parser = EpsonMaintenanceHTMLParser(
                    maintenance_html_text
                )
            else:
                self._maintenance_parser = None

            self.available = True
            self._data = None  # invalidate cache
        except Exception as e:
            print(e)
            self.available = False
            self._main_parser = None
            self._maintenance_parser = None
            self._data = None

    def get_sensor_value(self, sensor: str) -> int | str | None:
        """Retrieves the value of a specified sensor from the parsed printer data."""
        self._ensure_parsed()
        data = self._data or {}

        result: int | str | None = None

        # Handle special sensors
        if sensor == "printer_status":
            result = data.get("printer_status") or "Unknown"
        elif sensor == "scanner_status":
            result = data.get("scanner_status") or "Unknown"
        elif sensor == "clean":
            result = data.get("maintenance_box")
        elif sensor == "ip_address":
            result = self._ip

        # Network diagnostics
        elif sensor in ("signal_strength", "ssid"):
            network = data.get("network", {})
            network_key = "Signal Strength" if sensor == "signal_strength" else "SSID"
            result = network.get(network_key) or "Unknown"

        # WiFi Direct diagnostics
        elif sensor == "wifi_direct_connection_method":
            wifi_direct = data.get("wifi_direct", {})
            result = wifi_direct.get("Connection Method") or "Unknown"

        # Page count metrics from MENTINFO
        elif sensor in (
            "total_pages",
            "bw_pages",
            "color_pages",
            "duplex_pages",
            "simplex_pages",
        ):
            page_counts = data.get("maintenance", {}).get("print_info", {})
            result = page_counts.get(sensor)

        # Default to ink sensors
        else:
            inks: dict[str, int] = data.get("inks") or {}
            result = inks.get(sensor)

        return result

    def _ensure_parsed(self) -> None:
        if self._data is not None:
            return

        # The main parser is required, so if it's missing, we consider the
        # device unparsable.
        if not self._main_parser:
            return
        try:
            self._data = self._main_parser.parse()
        except Exception:
            self._data = {}
            return

        # For the maintenance parser, it's optional. If it fails, we just skip
        # it and don't include maintenance data.
        if self._maintenance_parser:
            try:
                maint_data = self._maintenance_parser.parse()
                if maint_data:
                    self._data["maintenance"] = maint_data
            except Exception:
                pass
