import json
import stat

import pytest

from app.core.credentials import (
    ENV_API_KEY,
    Credentials,
    MissingCredential,
    Secret,
    load_credentials,
    write_user_credentials,
)


def test_secret_masks_in_repr_and_str():
    s = Secret("user_abcdefghijklmnop")
    assert "abcdefghijklmnop" not in repr(s)
    assert "abcdefghijklmnop" not in str(s)
    assert s.reveal() == "user_abcdefghijklmnop"


def test_secret_short_value_fully_masked():
    s = Secret("abc")
    assert repr(s) == "Secret(***)"
    assert "abc" not in repr(s)


def test_secret_empty_is_falsy():
    assert not Secret("")
    assert Secret("").masked() == "<empty>"


def test_credentials_require_raises_without_key():
    with pytest.raises(MissingCredential) as exc:
        Credentials(api_key=Secret("")).require()
    assert ENV_API_KEY in str(exc.value)


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_API_KEY, "from-env")
    assert load_credentials(tmp_path).api_key.reveal() == "from-env"


def test_dotenv_used_when_env_missing(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    monkeypatch.setattr("app.core.credentials.USER_CRED_PATH", tmp_path / "nope.json")
    (tmp_path / ".env").write_text(f"{ENV_API_KEY}=from-dotenv\n", encoding="utf-8")
    assert load_credentials(tmp_path).api_key.reveal() == "from-dotenv"


def test_dotenv_ignores_comments_and_quotes(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    monkeypatch.setattr("app.core.credentials.USER_CRED_PATH", tmp_path / "nope.json")
    (tmp_path / ".env").write_text(
        f"# 注释\n{ENV_API_KEY}=\"quoted-value\"\n", encoding="utf-8"
    )
    assert load_credentials(tmp_path).api_key.reveal() == "quoted-value"


def test_user_json_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    cred = tmp_path / "credentials.json"
    cred.write_text(json.dumps({ENV_API_KEY: "from-json"}), encoding="utf-8")
    monkeypatch.setattr("app.core.credentials.USER_CRED_PATH", cred)
    assert load_credentials(tmp_path).api_key.reveal() == "from-json"


def test_write_user_credentials_sets_600(monkeypatch, tmp_path):
    target = tmp_path / "emr" / "credentials.json"
    monkeypatch.setattr("app.core.credentials.USER_CRED_PATH", target)
    path = write_user_credentials("secret-key-value")
    assert path == target
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))[ENV_API_KEY] == "secret-key-value"
