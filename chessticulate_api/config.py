"""app.config

Configuration module for the API.

Classes:
    CONFIG
"""

import os

from dotenv import load_dotenv

load_dotenv()


class CONFIG:  # pylint: disable=too-few-public-methods
    """Configuration class"""

    app_name: str = os.environ.get("APP_NAME", "chessticulate-api-dev")
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")
    sql_echo: bool = os.environ.get("SQL_ECHO") == "TRUE"

    # "postgresql+asyncpg://<uname>:<pswd>@<hostname>/<dbname>
    conn_str: str = os.environ.get("SQL_CONN_STR", "sqlite+aiosqlite:///:memory:")
    token_ttl: int = int(os.environ.get("TOKEN_TTL", 7))
    secret: str = os.environ.get("APP_SECRET", "secret")
    algorithm: str = os.environ.get("APP_JWT_ALGO", "HS256")
