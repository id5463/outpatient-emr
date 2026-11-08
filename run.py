#!/usr/bin/env python3
"""启动服务。默认对外广播在 0.0.0.0:8000。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

VENDOR = Path(__file__).parent / "_vendor"
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))
sys.path.insert(0, str(Path(__file__).parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="门诊病历填写系统")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8085)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--ssl-certfile", default=None,
                        help="证书路径。给了就启用 HTTPS（浏览器才允许录音）")
    parser.add_argument("--ssl-keyfile", default=None, help="私钥路径")
    args = parser.parse_args()

    import uvicorn

    kwargs = dict(
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    if args.ssl_certfile and args.ssl_keyfile:
        kwargs["ssl_certfile"] = args.ssl_certfile
        kwargs["ssl_keyfile"] = args.ssl_keyfile

    uvicorn.run("app.web.app:app", **kwargs)


if __name__ == "__main__":
    main()
