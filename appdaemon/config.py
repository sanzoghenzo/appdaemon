"""AppDaemon configuration."""
from pathlib import Path
from typing import Callable, Any

import pytz
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core.core_schema import ValidationInfo


class ADConfig(BaseModel):
    """AppDaemon configuration."""

    load_distribution: str = "roundrobin"
    app_dir: str | None = None
    starttime: str | None = None
    latitude: float
    longitude: float
    elevation: int
    time_zone: str
    config_file: str | None = None
    config_dir: str | None = None
    timewarp: float = 1
    max_clock_skew: int = 1
    total_threads: int | None = None
    pin_apps: bool = True
    pin_threads: int | None = None  # TODO: gte 0
    thread_duration_warning_threshold: float = 10
    threadpool_workers: int = 10
    endtime: str | None = None
    loglevel: str = "INFO"
    api_port: int | None = None
    utility_delay: int = 1
    admin_delay: int = 1
    max_utility_skew: float = 2  # TODO: self.utility_delay * 2
    check_app_updates_profile: bool = False
    production_mode: bool = False
    invalid_config_warnings: bool = True
    use_toml: bool = False
    missing_app_warnings: bool = True
    log_thread_actions: bool = False
    qsize_warning_threshold: int = 50
    qsize_warning_step: int = 60
    qsize_warning_iterations: int = 10
    internal_function_timeout: int = 10
    use_dictionary_unpacking: bool = False
    use_stream: bool = False
    namespaces: dict = {}
    stop_function: Callable[[...], None] | None = None
    cert_verify: bool = True
    disable_apps: bool = False
    exclude_dirs: set[str] = Field(default_factory=set)
    module_debug: dict[str, str] = Field(default_factory=dict)
    uvloop: bool = False

    @property
    def apps(self) -> bool:
        return not self.disable_apps

    @property
    def tz(self) -> pytz.BaseTzInfo:
        return pytz.timezone(self.time_zone)

    def get_log_level(self, module: str) -> str:
        return self.module_debug.get(module, self.loglevel)

    @field_validator("exclude_dirs")
    @classmethod
    def ensure_pychace_excluded(cls, v: set[str], info: ValidationInfo) -> set[str]:
        """Ensures that __pycache__ is always in the directories to exclude"""
        v.add("__pycache__")
        return v


class RssFeed(BaseModel):
    """RssFeed configuration."""

    feed: str
    target: str


ASSETS_DIR = Path(__file__).parent / "assets"


class BaseHTTPSettings(BaseModel):
    config_dir: Path
    javascript_dir: Path = ASSETS_DIR / "javascript"
    template_dir: Path = ASSETS_DIR / "templates"
    css_dir: Path = ASSETS_DIR / "css"
    fonts_dir: Path = ASSETS_DIR / "fonts"
    images_dir: Path = ASSETS_DIR / "images"
    webfonts_dir: Path = ASSETS_DIR / "webfonts"
    transport: str = "ws"


class HADashboardConfig(BaseHTTPSettings):
    """HADashboard configuration."""

    dashboard: bool = True
    profile_dashboard: bool = False
    config_file: str
    compile_on_start: bool = True
    force_compile: bool = False
    rss_feeds: list = Field(default_factory=list)
    rss_update: int | None = None
    fa4compatibility: bool = False
    stats_update: str = "realtime"
    title: str = "HADashboard"
    dashboard_dir: Path | None = None
    compile_dir: Path | None = None
    base_url: str = ""
    max_include_depth: int = 10

    @model_validator(mode="before")
    def default_val(cls, values: dict[str, Any]) -> dict[str, Any]:
        config_dir = Path(values["config_dir"])
        if values.get("dashboard_dir") is None:
            values["dashboard_dir"] = config_dir / "dashboards"
        if values.get("compile_dir") is None:
            values["compile_dir"] = config_dir / "compiled"
        return values

    @property
    def compiled_javascript_dir(self) -> Path:
        return self.compile_dir / "javascript"

    @property
    def compiled_css_dir(self) -> Path:
        return self.compile_dir / "css"

    @property
    def compiled_html_dir(self) -> Path:
        return self.compile_dir / "html"


class OldAdminConfig(BaseModel):
    """Admin configuration."""

    title: str = "AppDaemon Administrative Interface"


class AdminConfig(OldAdminConfig):
    """Admin configuration."""

    aui_dir: Path = ASSETS_DIR / "aui"
    aui_css_dir: Path = ASSETS_DIR / "aui" / "css"
    aui_js_dir: Path = ASSETS_DIR / "aui" / "js"


class HTTPConfig(BaseModel):
    """HTTP configuration."""

    url: str  # TODO: should be a non empty string
    password: str | None = None
    tokens: list[str] | None = None
    work_factor: int = 12
    ssl_certificate: str | None = None
    ssl_key: str | None = None
    transport: str = "ws"
    static_dirs: dict[str, str] = Field(default_factory=dict)
