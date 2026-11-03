"""python -m thermo [--port N] [--fake] [--no-browser] [--data DIR]"""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("thermo")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m thermo", description="PC temperature & performance monitor")
    p.add_argument("--port", type=int, help="port to listen on (default: settings, then 8000)")
    p.add_argument("--fake", action="store_true", help="use sample data instead of real sensors")
    p.add_argument("--no-browser", action="store_true", help="don't open the browser")
    p.add_argument("--data", type=Path, default=ROOT / "data", help="folder for the database, settings and log")
    return p.parse_args(argv)


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _machine(fake: bool) -> dict:
    info = {"host": socket.gethostname(), "model": "IdeaPad 5 Pro 16ARH7",
            "cpu": "Ryzen 7 6800HS", "gpu": "RTX 3050"}
    if fake:
        return info
    try:
        import wmi

        system = wmi.WMI().Win32_ComputerSystem()[0]
        info["model"] = system.SystemFamily or system.Model
    except Exception as exc:  # COM errors come in many types; the default label is fine
        log.warning("Could not read the laptop model: %s", exc)
    return info


def _setup_logging(data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(data / "thermo.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(logging.INFO)


def build_state(args: argparse.Namespace):
    from thermo import settings as settings_mod
    from thermo.alerts import AlertEngine, WinotifyNotifier
    from thermo.buffers import UsageBuffers
    from thermo.cooling import Cooling, SmartCooling
    from thermo.sampler import Sampler
    from thermo.server import AppState
    from thermo.store import Store

    settings_path = args.data / "settings.json"
    settings = settings_mod.load(settings_path)

    if args.fake:
        from thermo.fake import FakePowerApi, FakeSources, seed_history

        sources = FakeSources(no_fans=os.environ.get("THERMO_FAKE_NO_FANS") == "1")
        api, store = FakePowerApi(), Store(":memory:")
        seed_history(store, time.time())

        class _Quiet:
            def notify(self, title, body):
                log.info("(fake) toast: %s — %s", title, body)

        notifier = _Quiet()
    else:
        from thermo.cooling import WinPowerApi
        from thermo.sources import Sources

        sources, api = Sources(ROOT / "lib"), WinPowerApi()
        store, notifier = Store(args.data / "thermo.db"), WinotifyNotifier()

    cooling = Cooling(api, store)
    alerts = AlertEngine(settings.thresholds, notifier, store)
    smart = SmartCooling(cooling, settings.smart)
    buffers = UsageBuffers()
    sampler = Sampler(sources, store, alerts, cooling, smart, buffers)
    return AppState(sampler=sampler, store=store, buffers=buffers, cooling=cooling, smart=smart, alerts=alerts,
                    settings=settings, settings_path=settings_path, token=secrets.token_urlsafe(32),
                    is_admin=True if args.fake else _is_admin(), lhm_error=sources.lhm_error, machine=_machine(args.fake),
                    request_quit=lambda: None)


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    _setup_logging(args.data)
    from thermo import settings as settings_mod

    port = args.port or settings_mod.load(args.data / "settings.json").port
    if not _port_free(port):
        print(f"Port {port} is already in use. Start with --port {port + 1} or change it in Settings.",
              file=sys.stderr)
        raise SystemExit(1)

    import uvicorn

    from thermo.server import create_app

    state = build_state(args)
    server = uvicorn.Server(uvicorn.Config(create_app(state), host="127.0.0.1", port=port, log_level="warning"))
    state.request_quit = lambda: setattr(server, "should_exit", True)

    url = f"http://127.0.0.1:{port}/"
    print(f"Thermo is running at {url}  (Ctrl+C to stop)")
    if not state.is_admin and not args.fake:
        print("Not running as administrator: CPU and SSD temperatures will be missing. Use start.bat.")
    state.sampler.start()
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, (url,)).start()
    try:
        server.run()
    finally:
        state.sampler.stop()


if __name__ == "__main__":
    main()
