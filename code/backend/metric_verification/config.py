"""配置只在服务端读取；返回客户端时不含地址、账号或口令。"""
from dataclasses import dataclass
import os
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CODE = BACKEND.parent
ASSETS = CODE / "metric-verification"


def load_environment(path: Path | None = None) -> None:
    path = path or Path(os.getenv("MV_CONFIG_FILE", str(BACKEND / ".env.metric-verification")))
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("MV_"):
            # No interpolation, shell expansion, or logging of values.
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class DatabaseConfig:
    engine: str
    host: str
    port: int
    database: str
    user: str
    password: str
    service_name: str = ""
    ssl_ca: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password and
                    (self.service_name if self.engine == "oracle" else self.database))


def database_config(layer: str) -> DatabaseConfig:
    prefix = "MV_SOURCE" if layer == "source" else "MV_ANALYTICS"
    engine = os.getenv(prefix + "_ENGINE", "mysql").lower()
    return DatabaseConfig(
        engine=engine, host=os.getenv(prefix + "_HOST", ""),
        port=int(os.getenv(prefix + "_PORT", "1521" if engine == "oracle" else "3306")),
        database=os.getenv(prefix + "_DATABASE", "edu_source" if layer == "source" else "edu_analytics_v3"),
        user=os.getenv(prefix + "_USER", ""), password=os.getenv(prefix + "_PASSWORD", ""),
        service_name=os.getenv(prefix + "_SERVICE_NAME", ""), ssl_ca=os.getenv(prefix + "_SSL_CA", ""),
    )


def query_timeout() -> int:
    return max(1, min(60, int(os.getenv("MV_QUERY_TIMEOUT_SECONDS", "15"))))


def environment_name() -> str:
    return os.getenv("MV_ENVIRONMENT", "114测试环境")
