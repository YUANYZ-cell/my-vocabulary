from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from vocabulary.http_app import create_server


ROOT = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description="启动我的词汇本")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "vocabulary.db")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--idle-timeout", type=int, default=900)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = create_server(args.host, args.port, args.database, ROOT / "app", args.idle_timeout)
    server.start_idle_monitor()
    url = f"http://{args.host}:{server.server_port}/"
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    print(f"我的词汇本正在运行：{url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
