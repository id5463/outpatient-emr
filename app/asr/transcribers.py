"""ASR 后端。每个后端只做「音频 -> Transcript」，互相不知道对方存在。"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..core.contracts import Segment, Transcript


class MockTranscriber:
    """离线后端。优先读 <音频同名>.txt，否则返回内置对话。"""

    name = "mock"

    SAMPLE = (
        "医生：你好，请坐。今天哪里不舒服？\n"
        "患者：最近经常肚子痛，吃完饭以后更胀。\n"
        "医生：痛了多久？\n"
        "患者：大概一个星期，有时候还恶心。\n"
        "医生：以前有胃病吗？有没有腹泻或者发烧？\n"
        "患者：没有胃病，也没发烧。最近总吃辣的，不太按时吃饭。\n"
        "医生：先做个腹部检查，另外查一下血常规。\n"
        "患者：好的，我这情况严重吗？\n"
    )

    def available(self) -> bool:
        return True

    def transcribe(self, audio_path: Path, *, speakers: int = 2) -> Transcript:
        sidecar = audio_path.with_suffix(".txt")
        text = (
            sidecar.read_text(encoding="utf-8") if sidecar.is_file() else self.SAMPLE
        )
        return Transcript.from_text(text, backend=self.name)


class BailianTranscriber:
    """调用本机百炼 CLI。命令成功率最高的是异步 fun-asr。"""

    name = "bailian"

    def __init__(
        self,
        *,
        cli: str = "bl",
        cwd: str = "",
        models: tuple[str, ...] = ("fun-asr", "paraformer-v2"),
        timeout_s: int = 900,
    ) -> None:
        self.cli = cli
        self.cwd = cwd
        self.models = models
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return self._resolve_cli() is not None

    def _resolve_cli(self) -> str | None:
        if self.cwd:
            candidate = Path(self.cwd) / "node_modules" / ".bin" / self.cli
            if candidate.is_file():
                return str(candidate)
        return shutil.which(self.cli)

    def transcribe(self, audio_path: Path, *, speakers: int = 2) -> Transcript:
        exe = self._resolve_cli()
        if exe is None:
            raise RuntimeError(f"找不到 ASR CLI: {self.cli}")

        errors: list[str] = []
        for model in self.models:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "asr.json"
                cmd = [
                    exe,
                    "speech",
                    "recognize",
                    "--url",
                    str(audio_path.resolve()),
                    "--model",
                    model,
                    "--diarization",
                    "--speaker-count",
                    str(speakers),
                    "--language",
                    "zh",
                    "--timeout",
                    "300",
                    "--out",
                    str(out),
                ]
                proc = subprocess.run(
                    cmd,
                    cwd=self.cwd or None,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                )
                if proc.returncode != 0 or not out.is_file():
                    errors.append((proc.stderr or proc.stdout or "").strip()[-300:])
                    continue
                data = json.loads(out.read_text(encoding="utf-8"))
                return _from_bailian(data, model)

        raise RuntimeError("ASR 全部模型失败 -> " + " | ".join(errors))


def _from_bailian(data: dict, model: str) -> Transcript:
    segments: list[Segment] = []
    for item in (data.get("transcripts") or [])[:1]:
        for sent in item.get("sentences") or []:
            text = (sent.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                Segment(
                    text=text,
                    begin_ms=int(sent.get("begin_time") or 0),
                    end_ms=int(sent.get("end_time") or 0),
                    speaker=int(sent.get("speaker_id") or 0),
                )
            )
    return Transcript(segments=segments, backend="bailian", model=model)


def pick_transcriber(preference: str, **kwargs) -> object:
    """按偏好挑后端。auto 时优先真实转写，都不可用退回 mock。"""
    preference = (preference or "auto").lower()
    if preference == "mock":
        return MockTranscriber()
    if preference == "bailian":
        return BailianTranscriber(**kwargs)

    real = BailianTranscriber(**kwargs)
    return real if real.available() else MockTranscriber()
