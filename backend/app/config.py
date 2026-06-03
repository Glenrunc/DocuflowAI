from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://docuflow:docuflow@localhost:5432/docuflow"

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    # Embedding model for the agentic RAG vector store.
    ollama_embed_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # docTR runs on GPU when available; set to "cpu" to force the degraded fallback.
    ocr_device: str = "cuda"

    storage_dir: Path = REPO_ROOT / "backend" / "storage"
    shared_schema_path: Path = REPO_ROOT / "shared" / "schemas.json"

    worker_poll_interval: float = 1.0
    duplicate_threshold: float = 0.85
    agent_max_steps: int = 4
    agent_top_k: int = 5


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
