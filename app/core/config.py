"""配置。纯数据，没有任何 import 指向能力层。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
OUTPUT_DIR = PROJECT_ROOT / "out"
DEFAULT_BASE_URL = "https://api.commandcode.ai/provider/v1"


@dataclass(frozen=True)
class Settings:
    """一次运行所需的全部配置。不可变，测试时整体替换。"""

    base_url: str = DEFAULT_BASE_URL

    # 大模型候选链：第一个不可用顺延下一个，都是同量级小模型
    llm_models: tuple[str, ...] = (
        "Qwen/Qwen3.8-27B",
        "Qwen/Qwen3.8-Flash",
        "deepseek/deepseek-v4.1-flash",
        "z-ai/glm-5.3-flash",
    )
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192
    render_temperature: float = 0.2

    # 决策模型候选链
    decision_models: tuple[str, ...] = ("typesafe/jev", "typesafe/jev-1.14.0")

    # ASR
    asr_backend: str = "auto"  # auto | bailian | mock
    asr_models: tuple[str, ...] = ("fun-asr", "paraformer-v2")
    asr_speakers: int = 2
    bailian_cli: str = "bl"
    bailian_cwd: str = "/tmp/bltest"
    asr_timeout_s: int = 900

    # 端到端时间预算：一次生成必须在 5 分钟内完成
    budget_s: float = 300.0
    # 单次 HTTP 请求上限，需小于总预算，留出其它步骤的空间
    timeout_s: float = 150.0
    max_retries: int = 4
    retry_base_s: float = 1.5
    proxy: str = ""

    prompt_dir: Path = field(default=PROMPTS_DIR)
    output_dir: Path = field(default=OUTPUT_DIR)

    @classmethod
    def from_env(cls) -> "Settings":
        def _tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
            raw = os.getenv(name, "").strip()
            if not raw:
                return default
            return tuple(x.strip() for x in raw.split(",") if x.strip())

        return cls(
            base_url=os.getenv("EMR_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            llm_models=_tuple("EMR_LLM_MODELS", cls.llm_models),
            decision_models=_tuple("EMR_DECISION_MODELS", cls.decision_models),
            asr_backend=os.getenv("EMR_ASR_BACKEND", cls.asr_backend),
            asr_speakers=int(os.getenv("EMR_ASR_SPEAKERS", cls.asr_speakers)),
            bailian_cli=os.getenv("EMR_BAILIAN_CLI", cls.bailian_cli),
            bailian_cwd=os.getenv("EMR_BAILIAN_CWD", cls.bailian_cwd),
            budget_s=float(os.getenv("EMR_BUDGET", cls.budget_s)),
            timeout_s=float(os.getenv("EMR_TIMEOUT", cls.timeout_s)),
            max_retries=int(os.getenv("EMR_MAX_RETRIES", cls.max_retries)),
            proxy=os.getenv("EMR_PROXY", ""),
            prompt_dir=Path(os.getenv("EMR_PROMPT_DIR", str(PROMPTS_DIR))),
            output_dir=Path(os.getenv("EMR_OUTPUT_DIR", str(OUTPUT_DIR))),
        )
