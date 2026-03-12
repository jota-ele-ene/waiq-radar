"""
Carga config.yaml y variables de entorno.
"""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

def load_config(config_path: str = None) -> dict:
    """Carga la configuración desde YAML y .env"""
    load_dotenv()

    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Inyectar secrets desde env vars
    config["llm"]["api_key"] = _get_llm_key(config["llm"]["provider"])
    config["search"]["api_key"] = _get_search_key(config["search"]["provider"])

    if config["email"]["enabled"]:
        config["email"]["smtp"]["username"] = (
            os.getenv("SMTP_USERNAME") or config["email"]["smtp"].get("username", "")
        )
        config["email"]["smtp"]["password"] = (
            os.getenv("SMTP_PASSWORD") or config["email"]["smtp"].get("password", "")
        )

    if config["github"]["enabled"]:
        config["github"]["token"] = os.getenv("GITHUB_TOKEN", "")

    return config


def _get_llm_key(provider: str) -> str:
    keys = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    env_var = keys.get(provider, "OPENAI_API_KEY")
    return os.getenv(env_var, "")


def _get_search_key(provider: str) -> str:
    keys = {
        "serper": "SERPER_API_KEY",
        "tavily": "TAVILY_API_KEY",
        "searxng": "SEARXNG_URL",
    }
    env_var = keys.get(provider, "SERPER_API_KEY")
    return os.getenv(env_var, "")
