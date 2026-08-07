from pathlib import Path
from typing import ClassVar, Dict, Optional, Type

from har_reproducer.contracts import HttpTransport
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
            http_transport: Optional[HttpTransport] = None,
    ) -> Engine:
        engine_cls: Type[Engine] = cls.resolve_class(mode)
        transport: Optional[HttpTransport] = http_transport if engine_cls.USES_NETWORK else None
        if engine_cls.USES_NETWORK:
            assert transport is not None
        return engine_cls(har_path, output_dir, config_path=config_path, http_transport=transport)
