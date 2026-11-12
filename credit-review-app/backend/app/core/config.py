import warnings
from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # --- 应用 ---
    APP_MODE: Literal["real", "test"] = "real"
    PROJECT_NAME: str = "信贷资料核对"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str
    BIND_HOST: str = "127.0.0.1"
    API_PORT: int = 8080
    PUBLIC_ORIGIN: str = "http://localhost:8080"

    # --- 会话 ---
    SESSION_HOURS: int = 8
    SESSION_COOKIE_SECURE: bool = False

    # --- 数据库 ---
    DATABASE_URL: str
    POSTGRES_PASSWORD: str = ""

    # --- 存储与流水线 ---
    DATA_DIR: str = "/data"
    PIPELINE_CONFIG_VERSION: str = "pipeline-v1"

    # --- 初始账号 ---
    INITIAL_USERS_JSON: str = "[]"

    # --- 上传限额（工程初始值） ---
    UPLOAD_MAX_FILES_PER_TASK: int = 50
    UPLOAD_MAX_FILE_BYTES: int = 52_428_800  # 50MiB
    UPLOAD_MAX_TASK_BYTES: int = 314_572_800  # 300MiB
    UPLOAD_MAX_FILE_PAGES: int = 500
    UPLOAD_MAX_TASK_PAGES: int = 1000

    # --- OCR（P2+ 使用，缺失不阻塞登录/查看任务） ---
    OCR_JOB_URL: str = ""
    OCR_ACCESS_TOKEN: str = ""
    OCR_MODEL: str = "PaddleOCR-VL-1.6"
    OCR_POLL_INTERVAL_SECONDS: int = 5
    OCR_TOTAL_TIMEOUT_SECONDS: int = 1800
    OCR_REQUEST_TIMEOUT_SECONDS: int = 60
    OCR_CONNECT_TIMEOUT_SECONDS: int = 10
    OCR_MAX_ACTIVE_JOBS: int = 1
    OCR_JSONL_MAX_BYTES: int = 104_857_600
    OCR_IMAGE_MAX_BYTES: int = 20_971_520
    OCR_IMAGE_MAX_PIXELS: int = 40_000_000
    OCR_TASK_ARTIFACT_MAX_BYTES: int = 2_147_483_648
    OCR_IMAGE_HOSTS: list[str] = ["pplines-online.bj.bcebos.com"]

    # --- LLM（P2+ 使用） ---
    LLM_API_BASE: str = ""
    LLM_API_KEY: str = ""
    LLM_TEXT_MODEL: str = ""
    LLM_VISION_MODEL: str = ""
    LLM_REQUEST_TIMEOUT_SECONDS: int = 120
    LLM_CONNECT_TIMEOUT_SECONDS: int = 10
    LLM_MAX_CONCURRENCY: int = 2
    LLM_MAX_TRANSIENT_RETRIES: int = 2
    LLM_MAX_FORMAT_REPAIRS: int = 1
    LLM_MAX_OUTPUT_TOKENS: int = 4096
    LLM_WINDOW_CHARACTERS: int = 8000
    LLM_WINDOW_OVERLAP_CHARACTERS: int = 500
    VISION_IMAGES_PER_BATCH: int = 4
    VISION_MAX_IMAGE_EDGE: int = 1600

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: str) -> str:
        database_url = str(value)
        for scheme in ("postgres://", "postgresql://"):
            if database_url.startswith(scheme):
                return database_url.replace(scheme, "postgresql+psycopg://", 1)
        return database_url

    @model_validator(mode="after")
    def _warn_default_secret(self) -> Self:
        if self.APP_MODE == "real" and self.SECRET_KEY == "CHANGE_ME_TO_A_RANDOM_LONG_SECRET":
            warnings.warn(
                "SECRET_KEY 仍为占位值，请替换为随机长密钥。",
                stacklevel=1,
            )
        return self

    @property
    def ocr_configured(self) -> bool:
        return bool(self.OCR_JOB_URL and self.OCR_ACCESS_TOKEN)

    @property
    def llm_configured(self) -> bool:
        return bool(self.LLM_API_BASE and self.LLM_API_KEY and self.LLM_TEXT_MODEL)


settings = Settings()  # type: ignore[call-arg]
