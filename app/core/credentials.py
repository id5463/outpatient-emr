"""凭据管理。

职责边界：
  这里只负责「凭据从哪来、是否齐备、绝不写进日志/响应」。
  Settings（config.py）只描述非敏感的运行参数，不保存任何密钥。

查找顺序（先找到先用）：
  1. 环境变量
  2. .env 文件（项目根，已在 .gitignore 里忽略）
  3. ~/.config/emr/credentials.json

所有读取结果都包在 Secret 里，repr/str 一律打码，避免误打进日志。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ENV_API_KEY = "EMR_API_KEY"
DOTENV_NAME = ".env"
USER_CRED_PATH = Path.home() / ".config" / "emr" / "credentials.json"


@dataclass(frozen=True)
class Secret:
    """打码的字符串。取真值必须显式调用 reveal()。"""

    _value: str = ""

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __len__(self) -> int:
        return len(self._value)

    def __repr__(self) -> str:
        return f"Secret({self.masked()})"

    __str__ = __repr__

    def masked(self) -> str:
        v = self._value
        if not v:
            return "<empty>"
        if len(v) <= 12:
            return "*" * len(v)
        return f"{v[:6]}...{v[-4:]}"


@dataclass(frozen=True)
class Credentials:
    """一次运行用到的全部密钥。"""

    api_key: Secret

    def require(self, name: str = "api_key") -> str:
        secret: Secret = getattr(self, name)
        if not secret:
            raise MissingCredential(
                f"缺少 {name}。设置环境变量 {ENV_API_KEY}，"
                f"或在项目根写 {DOTENV_NAME}，或写入 {USER_CRED_PATH}"
            )
        return secret.reveal()

    def summary(self) -> dict[str, str]:
        return {"api_key": self.api_key.masked()}


class MissingCredential(RuntimeError):
    pass


def load_credentials(project_root: Path | None = None) -> Credentials:
    env = dict(os.environ)
    key = env.get(ENV_API_KEY, "")

    if not key and project_root is not None:
        key = _from_dotenv(project_root / DOTENV_NAME).get(ENV_API_KEY, "")

    if not key:
        key = _from_json(USER_CRED_PATH).get(ENV_API_KEY, "")

    return Credentials(api_key=Secret(key.strip()))


def _from_dotenv(path: Path) -> dict[str, str]:
    """只解析 KEY=VALUE，不引入额外依赖。"""
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def _from_json(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def write_user_credentials(api_key: str) -> Path:
    """把 api key 写进用户级配置文件，权限 600。"""
    USER_CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_CRED_PATH.write_text(
        json.dumps({ENV_API_KEY: api_key}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    USER_CRED_PATH.chmod(0o600)
    return USER_CRED_PATH
