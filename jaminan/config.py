"""Runtime configuration. On Vercel every value is an environment variable; locally, scripts and
tests may fill missing values from ~/.config/<tool>/*.env (never from files in this repo)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

LOCAL_ENV_FILES = {
    "paypal": "~/.config/paypal/sandbox.env",
    "upstash": "~/.config/upstash/rekindle.env",
    "qwen": "~/.config/qwen/qwen.env",
}


def load_local_env() -> None:
    """Fill os.environ from the builder's ~/.config files without overriding anything already set."""
    for path in LOCAL_ENV_FILES.values():
        p = Path(path).expanduser()
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.environ.get(name, default).split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    paypal_base: str = field(default_factory=lambda: os.environ.get(
        "PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com").rstrip("/"))
    paypal_client_id: str = field(default_factory=lambda: os.environ.get("PAYPAL_CLIENT_ID", ""))
    paypal_client_secret: str = field(default_factory=lambda: os.environ.get("PAYPAL_CLIENT_SECRET", ""))
    paypal_webhook_id: str = field(default_factory=lambda: os.environ.get("PAYPAL_WEBHOOK_ID", ""))
    redis_url: str = field(default_factory=lambda: os.environ.get("UPSTASH_REDIS_REST_URL", ""))
    redis_token: str = field(default_factory=lambda: os.environ.get("UPSTASH_REDIS_REST_TOKEN", ""))
    key_prefix: str = field(default_factory=lambda: os.environ.get("JAMINAN_KEY_PREFIX", "jaminan:"))
    qwen_key: str = field(default_factory=lambda: os.environ.get("QWEN_API_KEY", ""))
    qwen_base: str = field(default_factory=lambda: os.environ.get(
        "QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1").rstrip("/"))
    # The model the service asks for. Only BENCHMARKED_MODEL can produce a chargeable line;
    # it stays empty until the vision bench on the staged set pins one.
    vision_model: str = field(default_factory=lambda: os.environ.get("JAMINAN_VISION_MODEL", "qwen3-vl-plus"))
    benchmarked_model: str = field(default_factory=lambda: os.environ.get("JAMINAN_BENCHMARKED_MODEL", ""))
    chargeable_classes: tuple[str, ...] = field(default_factory=lambda: _csv(
        "JAMINAN_CHARGEABLE_CLASSES", "missing_part,broken_part,crack,dent"))
    confidence_floor: float = field(default_factory=lambda: float(os.environ.get("JAMINAN_CONFIDENCE_FLOOR", "0.7")))
    judge_vault_ids: tuple[str, ...] = field(default_factory=lambda: _csv("JUDGE_VAULT_IDS", ""))
    judge_buyer_email: str = field(default_factory=lambda: os.environ.get("JUDGE_BUYER_EMAIL", ""))
    judge_buyer_password: str = field(default_factory=lambda: os.environ.get("JUDGE_BUYER_PASSWORD", ""))
    app_url: str = field(default_factory=lambda: os.environ.get("APP_URL", "http://localhost:3000").rstrip("/"))
    cron_secret: str = field(default_factory=lambda: os.environ.get("CRON_SECRET", ""))

    def __post_init__(self) -> None:
        if "sandbox" not in self.paypal_base:
            raise RuntimeError("Jaminan runs on the PayPal sandbox only; PAYPAL_API_BASE must be a sandbox URL")


def settings() -> Settings:
    return Settings()
