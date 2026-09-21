"""Start the local-only admin app on the first available loopback port."""
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def choose_port(first=8502, last=8511):
    for port in range(first, last + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"관리자용 포트 {first}~{last}가 모두 사용 중입니다.")


def main():
    try:
        port = choose_port()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    environment = os.environ.copy()
    environment["ESTATE_ADMIN_LOCAL"] = "1"
    print(f"관리자 주소: http://127.0.0.1:{port}", flush=True)
    return subprocess.call([
        sys.executable, "-m", "streamlit", "run", str(ROOT / "admin.py"),
        "--server.address", "127.0.0.1", "--server.port", str(port),
    ], cwd=ROOT, env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
