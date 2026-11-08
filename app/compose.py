"""组装层。唯一知道「具体用哪个实现」的地方。

config 与 credentials 只提供数据，各层的具体实现在这里被拼起来。
Web 层和 CLI 都从这里取，不自己 new 任何客户端。
"""

from __future__ import annotations

from functools import lru_cache

from .asr.transcribers import pick_transcriber
from .core.config import PROJECT_ROOT, Settings
from .core.credentials import load_credentials
from .core.transport import JsonTransport
from .decision.jev import JevJudger
from .llm.chat import QwenChat
from .llm.prompts import FilePromptSource
from .pipeline.record_pipeline import RecordPipeline
from .storage.writer import FileRecordWriter


def build_transport(settings: Settings, api_key: str) -> JsonTransport:
    return JsonTransport(
        settings.base_url,
        api_key,
        timeout_s=settings.timeout_s,
        max_retries=settings.max_retries,
        retry_base_s=settings.retry_base_s,
        proxy=settings.proxy,
    )


def build_pipeline(settings: Settings) -> RecordPipeline:
    """按配置组装一条流水线。缺凭据时在这里就报错，不要等到调用模型。"""
    api_key = load_credentials(PROJECT_ROOT).require()
    transport = build_transport(settings, api_key)

    return RecordPipeline(
        transcriber=pick_transcriber(
            settings.asr_backend,
            cli=settings.bailian_cli,
            cwd=settings.bailian_cwd,
            models=settings.asr_models,
            timeout_s=settings.asr_timeout_s,
        ),
        chat=QwenChat(transport, settings.llm_models),
        judger=JevJudger(transport, settings.decision_models),
        prompts=FilePromptSource(settings.prompt_dir),
        writer=FileRecordWriter(settings.output_dir),
        speakers=settings.asr_speakers,
        llm_temperature=settings.llm_temperature,
        llm_max_tokens=settings.llm_max_tokens,
        budget_s=settings.budget_s,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache(maxsize=1)
def get_pipeline() -> RecordPipeline:
    return build_pipeline(get_settings())
