from __future__ import annotations

import threading
import webbrowser
from collections.abc import Collection
from pathlib import Path
from urllib.parse import urlencode

from .assembly_webui.server import AssemblyApplication, AssemblyServer
from .config import AppConfig
from .i18n import t
from .webui.server import ReviewApplication, ReviewServer


def serve_both_webuis(
    audio: str | Path | None,
    config: AppConfig,
    *,
    project_name: str | None,
    assembly_project_name: str | Collection[str] | None = None,
    webui1_port: int = 8765,
    webui2_port: int = 8766,
    open_browser: bool = True,
) -> None:
    """Run both local WebUIs in one process and stop them together."""
    for port in (webui1_port, webui2_port):
        if not 1 <= port <= 65535:
            raise ValueError(t("errors.port_range"))
    if webui1_port == webui2_port:
        raise ValueError(t("errors.ports_different"))

    review_app = ReviewApplication(Path(audio) if audio is not None else None, config, project_name=project_name)
    review_server: ReviewServer | None = None
    assembly_server: AssemblyServer | None = None
    threads: list[threading.Thread] = []
    started_servers: list[ReviewServer | AssemblyServer] = []
    try:
        review_server = ReviewServer(("127.0.0.1", webui1_port), review_app)
        assembly_server = AssemblyServer(("127.0.0.1", webui2_port), AssemblyApplication(config))
        review_url = f"http://127.0.0.1:{review_server.server_port}/"
        if assembly_project_name is None:
            assembly_query = urlencode({"initial_blank": "1"})
        else:
            names = ([assembly_project_name] if isinstance(assembly_project_name, str)
                     else list(assembly_project_name))
            assembly_query = urlencode(
                [("initial_project", name) for name in names], doseq=True
            )
        assembly_url = f"http://127.0.0.1:{assembly_server.server_port}/?{assembly_query}"
        print(t("server.review_url", url=review_url))
        print(t("server.assembly_url", url=assembly_url))
        print(t("server.stop_both"))

        for name, server in (("webui1", review_server), ("webui2", assembly_server)):
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.25},
                name=name,
                daemon=True,
            )
            thread.start()
            threads.append(thread)
            started_servers.append(server)
        if open_browser:
            webbrowser.open(review_url)
            webbrowser.open(assembly_url)
        try:
            while all(thread.is_alive() for thread in threads):
                threads[0].join(timeout=0.5)
        except KeyboardInterrupt:
            pass
    finally:
        for server in started_servers:
            server.shutdown()
        for server in (review_server, assembly_server):
            if server is not None:
                server.server_close()
        for thread in threads:
            thread.join(timeout=2)
        review_app.close()
