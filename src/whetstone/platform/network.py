"""The laptop's addresses a phone can reach: its LAN (Wi-Fi) address, or its Tailscale address."""

import shutil
import socket
import subprocess


def lan_address() -> str | None:
    """The address the OS would use to reach the local network, or None without one."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))  # a UDP connect sends nothing; it only picks the outgoing interface
        except OSError:
            return None
        address = probe.getsockname()[0]
    return None if address.startswith("127.") else address


class TailscaleMissing(Exception):
    pass


def tailscale_address() -> str:
    tailscale = shutil.which("tailscale")
    if tailscale is None:
        raise TailscaleMissing()
    return subprocess.run([tailscale, "ip", "-4"], capture_output=True, text=True, timeout=10, check=True).stdout.split()[0]


class TailscaleError(Exception):
    pass
