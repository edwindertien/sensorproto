"""
hokuyo_driver.py

Minimal SCIP2.0 driver for the Hokuyo URG-04LX-UG01, talking to the sensor
over its USB virtual serial port (shows up as /dev/tty.usbmodemXXXX on macOS).

Reference: Hokuyo SCIP 2.0 communication protocol. Distance values are
encoded as 3 printable ASCII characters per point, 6 bits each, offset
by 0x30, most-significant character first. The scanner exposes 1024 steps
per revolution (360 / 1024 deg/step); step 384 points straight ahead, and
the sensor's usable 240 degree field of view spans steps 44 to 725.

This has been written against the protocol spec but not yet run against
physical hardware -- before trusting distances, point the sensor at a
wall you've measured by hand and confirm get_scan() agrees.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator, List, Tuple

import serial

SCIP_ENCODE_OFFSET = 0x30
BITS_PER_CHAR = 6

START_STEP = 44
END_STEP = 725
FRONT_STEP = 384
STEPS_PER_REV = 1024
STEP_ANGLE_DEG = 360.0 / STEPS_PER_REV


class HokuyoError(RuntimeError):
    """Raised when the sensor replies with a non-success status code."""


@dataclass
class Scan:
    timestamp: float
    angles_deg: List[float]
    distances_mm: List[int]


def _decode(chars: str) -> int:
    value = 0
    for ch in chars:
        value = (value << BITS_PER_CHAR) | (ord(ch) - SCIP_ENCODE_OFFSET)
    return value


class HokuyoURG:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        self._ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        # Older firmware boots in SCIP1.1; this switches to SCIP2.0 and is a
        # harmless no-op if the sensor is already in that mode.
        self._command("SCIP2.0", expect_status=False)
        self._command("BM")  # laser on

    def close(self) -> None:
        try:
            self._command("QT", expect_status=False)
        except Exception:
            pass
        self._ser.close()

    def __enter__(self) -> "HokuyoURG":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- low level -----------------------------------------------------

    def _send_line(self, text: str) -> None:
        self._ser.write((text + "\n").encode("ascii"))

    def _read_line(self) -> str:
        raw = self._ser.readline()
        return raw.decode("ascii", errors="replace").rstrip("\n")

    def _read_block(self) -> List[str]:
        """Read lines until the blank line that terminates a reply."""
        lines = []
        while True:
            line = self._read_line()
            if line == "":
                break
            lines.append(line)
        return lines

    def _command(self, cmd: str, expect_status: bool = True) -> List[str]:
        self._send_line(cmd)
        lines = self._read_block()
        if not lines or lines[0] != cmd:
            raise HokuyoError(f"Echo mismatch for {cmd!r}: got {lines!r}")
        if expect_status:
            if len(lines) < 2 or not lines[1].startswith("00"):
                status = lines[1] if len(lines) > 1 else "<none>"
                raise HokuyoError(f"Sensor rejected {cmd!r}: status {status!r}")
        return lines

    @staticmethod
    def _points_from_payload(payload: str, cluster_count: int) -> Tuple[List[float], List[int]]:
        step_span = max(cluster_count, 1)
        angles, distances = [], []
        step = START_STEP
        # payload is 3-char-encoded distances back to back; trailing partial
        # groups (padding) are ignored.
        for i in range(0, len(payload) - 2, 3):
            distances.append(_decode(payload[i:i + 3]))
            angles.append((step - FRONT_STEP) * STEP_ANGLE_DEG)
            step += step_span
        return angles, distances

    # -- public API ------------------------------------------------------

    def get_scan(self, cluster_count: int = 0) -> Scan:
        """Request a single full-range scan (blocking)."""
        cmd = f"GD{START_STEP:04d}{END_STEP:04d}{cluster_count:02d}"
        lines = self._command(cmd)
        # lines[0]=echo, lines[1]=status, lines[2]=timestamp, rest=data
        data_lines = lines[3:]
        payload = "".join(line[:-1] for line in data_lines)  # drop per-line checksum char
        angles, distances = self._points_from_payload(payload, cluster_count)
        return Scan(timestamp=time.time(), angles_deg=angles, distances_mm=distances)

    def iter_scans(
        self,
        cluster_count: int = 0,
        scan_interval: int = 0,
        num_scans: int = 0,
    ) -> Iterator[Scan]:
        """Continuously stream scans via MD. num_scans=0 means unlimited."""
        cmd = f"MD{START_STEP:04d}{END_STEP:04d}{cluster_count:02d}{scan_interval:01d}{num_scans:02d}"
        self._send_line(cmd)
        lines = self._read_block()
        if not lines or lines[0] != cmd or not lines[1].startswith("00"):
            raise HokuyoError(f"Sensor rejected {cmd!r}: {lines!r}")

        count = 0
        while num_scans == 0 or count < num_scans:
            lines = self._read_block()
            if len(lines) < 4:
                continue  # transient hiccup; keep listening
            data_lines = lines[3:]
            payload = "".join(line[:-1] for line in data_lines)
            angles, distances = self._points_from_payload(payload, cluster_count)
            yield Scan(timestamp=time.time(), angles_deg=angles, distances_mm=distances)
            count += 1

    def stop_scanning(self) -> None:
        """Interrupt a running iter_scans() stream from another thread's view
        by sending QT; the generator's next read will then fail/stop."""
        self._send_line("QT")