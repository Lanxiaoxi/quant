"""全局配置：从环境变量 / backend/.env 读取。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # tushare Pro token（2000 积分）
    tushare_token: str = ""
    # 数据目录：行情 duckdb、业务 sqlite、回测结果
    data_dir: Path = ROOT_DIR / "data"
    # tushare 节流：每分钟最大调用次数（2000 积分各接口上限不同，保守取值）
    tushare_max_calls_per_minute: int = 90

    # 鉴权（单人使用）：默认账号 admin，密码走环境变量
    admin_username: str = "admin"
    admin_password: str = "admin"  # 部署时务必用环境变量覆盖
    jwt_secret: str = "trading-quant-dev-secret-change-me"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 天

    @property
    def duckdb_path(self) -> Path:
        return self.data_dir / "market.duckdb"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
