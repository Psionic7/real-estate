"""Fail-closed guard for the separate localhost-only collection application."""
import os


def local_admin_allowed(server_address=None, environ=None):
    environ = os.environ if environ is None else environ
    return (environ.get("ESTATE_ADMIN_LOCAL") == "1"
            and not environ.get("IS_STREAMLIT_CLOUD")
            and not environ.get("STREAMLIT_SHARING_MODE")
            and server_address == "127.0.0.1")
