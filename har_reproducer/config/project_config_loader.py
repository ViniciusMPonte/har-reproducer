from pathlib import Path
from typing import Optional

from pydantic import TypeAdapter

from har_reproducer.fs_io import Workspace
from har_reproducer.models import ProjectConfig


class ProjectConfigLoader:

    @staticmethod
    def load(config_path: Optional[Path]) -> ProjectConfig:
        config: ProjectConfig = ProjectConfigLoader._load_raw(config_path)
        return ProjectConfigLoader._apply_defaults(config)

    @staticmethod
    def _load_raw(config_path: Optional[Path]) -> ProjectConfig:
        if not config_path or not config_path.exists():
            return ProjectConfig()
        return ProjectConfigLoader._parse(config_path)

    @staticmethod
    def _parse(config_path: Path) -> ProjectConfig:
        try:
            adapter: TypeAdapter[ProjectConfig] = TypeAdapter(ProjectConfig)
            return adapter.validate_json(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error loading config: {e}")
            return ProjectConfig()

    @staticmethod
    def _apply_defaults(config: ProjectConfig) -> ProjectConfig:
        if config.ca_cert_path is None:
            config.ca_cert_path = Workspace.get_mitmproxy_ca_path()
        return config
