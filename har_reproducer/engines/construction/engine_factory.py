from pathlib import Path
from typing import ClassVar, Dict, Optional, Type

from har_reproducer.engines.dry_engine import DryEngine
from har_reproducer.engines.engine import Engine
from har_reproducer.engines.construction.engine_mode import EngineMode


class EngineFactory:
    _STRATEGIES: ClassVar[Dict[EngineMode, Type[Engine]]] = {
        EngineMode.MAIN: Engine,
        EngineMode.DRY: DryEngine,
    }

    @classmethod
    def resolve_class(cls, mode: EngineMode) -> Type[Engine]:
        return cls._STRATEGIES[mode]

    @classmethod
    def create(
            cls,
            mode: EngineMode,
            har_path: Path,
            output_dir: Path,
            config_path: Optional[Path],
            proxy_port: Optional[int] = None,
    ) -> Engine:
        engine_cls: Type[Engine] = cls.resolve_class(mode)
        return engine_cls(
            har_path,
            output_dir,
            config_path=config_path,
            proxy_port=proxy_port,
        )
