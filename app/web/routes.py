"""HTTP 接口。只做参数校验与响应组装，业务在 pipeline 里。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from ..compose import get_pipeline, get_settings
from ..core.credentials import MissingCredential
from ..llm.prompts import PromptNotFound

router = APIRouter()

ALLOWED_AUDIO = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".flac", ".amr"}
MAX_UPLOAD_BYTES = 60 * 1024 * 1024


class TextRequest(BaseModel):
    transcript: str = Field(..., min_length=1, description="角色：内容 格式的对话")
    visited_at: str | None = None
    persist: bool = True


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, MissingCredential):
        return HTTPException(status_code=503, detail=f"服务未配置凭据：{exc}")
    if isinstance(exc, PromptNotFound):
        return HTTPException(status_code=500, detail=f"提示词缺失：{exc}")
    return HTTPException(status_code=502, detail=f"生成失败：{exc}")


@router.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    try:
        pipeline = get_pipeline()
        ready = True
        asr = pipeline.transcriber.name
    except MissingCredential as exc:
        ready = False
        asr = ""
        return {
            "ok": False,
            "ready": False,
            "reason": str(exc),
            "models": {"llm": list(settings.llm_models), "decision": list(settings.decision_models)},
        }
    return {
        "ok": True,
        "ready": ready,
        "asr": asr,
        "models": {
            "llm": list(settings.llm_models),
            "decision": list(settings.decision_models),
        },
        "budget_s": settings.budget_s,
        "prompts": sorted(p.stem for p in settings.prompt_dir.glob("*.md")),
    }


@router.post("/api/record/text")
def generate_from_text(req: TextRequest) -> JSONResponse:
    """粘贴对话文本直接生成病历。"""
    try:
        result = get_pipeline().run(
            transcript_text=req.transcript,
            visited_at=req.visited_at,
            persist=req.persist,
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return JSONResponse(result.to_payload())


@router.post("/api/record/audio")
async def generate_from_audio(
    file: UploadFile = File(...),
    speakers: int = Form(2),
    persist: bool = Form(True),
) -> JSONResponse:
    """上传录音，转写后生成病历。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_AUDIO:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的音频格式：{suffix or '无扩展名'}，允许 {sorted(ALLOWED_AUDIO)}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="音频超过 60MB")

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = Path(tmp) / f"upload{suffix}"
        audio_path.write_bytes(data)
        try:
            pipeline = get_pipeline()
            pipeline.speakers = max(1, min(speakers, 4))
            result = pipeline.run(audio_path=audio_path, persist=persist)
        except Exception as exc:  # noqa: BLE001
            raise _handle(exc) from exc

    return JSONResponse(result.to_payload())


@router.get("/api/record/{stem}/markdown", response_class=PlainTextResponse)
def get_markdown(stem: str) -> str:
    """按文件名取历史产出的 Markdown。"""
    out_dir = get_settings().output_dir
    safe = Path(stem).name
    path = out_dir / (safe if safe.endswith(".md") else f"{safe}.md")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return path.read_text(encoding="utf-8")


@router.get("/api/records")
def list_records(limit: int = 20) -> dict[str, Any]:
    out_dir = get_settings().output_dir
    if not out_dir.exists():
        return {"items": []}
    files = sorted(out_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "items": [
            {"name": p.name, "stem": p.stem, "mtime": int(p.stat().st_mtime),
             "size": p.stat().st_size}
            for p in files[: max(1, min(limit, 100))]
        ]
    }


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    from .pages import INDEX_HTML

    return INDEX_HTML
