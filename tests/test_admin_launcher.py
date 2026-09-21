import socket

from scripts.launch_admin import choose_port


def test_admin_launcher_skips_occupied_loopback_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        assert choose_port(port, port + 10) != port
