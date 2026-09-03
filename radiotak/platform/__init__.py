"""Platform abstractions — Linux vs Windows/dev stub."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from abc import ABC, abstractmethod
from typing import Any, Optional


class Platform(ABC):
    @abstractmethod
    def system_info(self) -> dict[str, Any]: ...

    @abstractmethod
    def service_action(self, unit: str, action: str) -> tuple[int, str]: ...

    @abstractmethod
    def run_priv(self, *args: str) -> tuple[int, str]: ...

    @abstractmethod
    def list_sdr_devices(self) -> list[dict[str, Any]]: ...


class DevPlatform(Platform):
    """Runs on Windows / macOS / any non-Pi for UI development."""

    def system_info(self) -> dict[str, Any]:
        import psutil

        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "platform": "dev",
            "os": f"{platform.system()} {platform.release()}",
            "hostname": socket.gethostname(),
            "arch": platform.machine(),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / (1024**3), 2),
            "ram_total_gb": round(vm.total / (1024**3), 2),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "temp_c": None,
            "uptime": _fmt_uptime(psutil.boot_time()),
            "ips": _local_ips(),
            "ntp": "n/a",
            "pi_model": None,
        }

    def service_action(self, unit: str, action: str) -> tuple[int, str]:
        return 0, f"[dev] {action} {unit} (noop)"

    def run_priv(self, *args: str) -> tuple[int, str]:
        return 0, f"[dev] priv {' '.join(args)} (noop)"

    def list_sdr_devices(self) -> list[dict[str, Any]]:
        return [
            {
                "driver": "rtl",
                "name": "Simulated RTL-SDR",
                "serial_number": "DEV00001",
                "usb_path": "dev://0",
            }
        ]


class LinuxPlatform(Platform):
    def system_info(self) -> dict[str, Any]:
        import psutil

        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        temp = None
        try:
            temps = psutil.sensors_temperatures()
            for _name, entries in (temps or {}).items():
                if entries:
                    temp = entries[0].current
                    break
        except Exception:  # noqa: BLE001
            pass
        if temp is None:
            try:
                t = open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8").read().strip()
                temp = int(t) / 1000.0
            except Exception:  # noqa: BLE001
                pass
        model = None
        try:
            model = open("/proc/device-tree/model", encoding="utf-8").read().replace("\x00", "").strip()
        except Exception:  # noqa: BLE001
            pass
        return {
            "platform": "linux",
            "os": f"{platform.system()} {platform.release()}",
            "hostname": socket.gethostname(),
            "arch": platform.machine(),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / (1024**3), 2),
            "ram_total_gb": round(vm.total / (1024**3), 2),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "temp_c": temp,
            "uptime": _fmt_uptime(psutil.boot_time()),
            "ips": _local_ips(),
            "ntp": _ntp_status(),
            "pi_model": model,
        }

    def service_action(self, unit: str, action: str) -> tuple[int, str]:
        return self.run_priv("systemctl", action, unit)

    def run_priv(self, *args: str) -> tuple[int, str]:
        helper = shutil.which("radiotak-priv") or "/opt/radiotak/bin/radiotak-priv"
        cmd = ["sudo", "-n", helper, *args]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
            out = (proc.stdout or "") + (proc.stderr or "")
            return proc.returncode, out.strip()
        except Exception as exc:  # noqa: BLE001
            return 1, str(exc)

    def list_sdr_devices(self) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        try:
            proc = subprocess.run(["lsusb"], capture_output=True, text=True, check=False)
            for line in (proc.stdout or "").splitlines():
                low = line.lower()
                if "0bda:2838" in low or "rtl" in low:
                    devices.append(
                        {
                            "driver": "rtl",
                            "name": "RTL2832 SDR",
                            "serial_number": None,
                            "usb_path": line.strip(),
                        }
                    )
                elif "1d50:60a1" in low or "airspy" in low:
                    devices.append(
                        {
                            "driver": "airspy",
                            "name": "Airspy",
                            "serial_number": None,
                            "usb_path": line.strip(),
                        }
                    )
        except Exception:  # noqa: BLE001
            pass
        return devices


def _local_ips() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ":" not in ip and not ip.startswith("127."):
                if ip not in ips:
                    ips.append(ip)
    except Exception:  # noqa: BLE001
        pass
    return ips


def _fmt_uptime(boot_time: float) -> str:
    import time

    secs = int(time.time() - boot_time)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def _ntp_status() -> str:
    try:
        proc = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
        val = (proc.stdout or "").strip()
        return "synced" if val == "yes" else val or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


_platform: Optional[Platform] = None


def get_platform() -> Platform:
    global _platform
    if _platform is None:
        if os.name == "nt" or platform.system() != "Linux":
            _platform = DevPlatform()
        else:
            _platform = LinuxPlatform()
    return _platform
