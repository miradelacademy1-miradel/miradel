import os


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./dev.db")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _db_url()
ENV = os.getenv("ENV", "dev")
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if ENV == "prod":
        raise RuntimeError("SECRET_KEY oʻrnatilmagan (Railway Variables)")
    SECRET_KEY = "dev-only-secret-change-me"
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))
PASSWORD_LENGTH = max(6, int(os.getenv("PASSWORD_LENGTH", "6")))
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
