from pathlib import Path
from typing import ClassVar, Dict, Optional, Type

from ..dry_engine import DryEngine
from ..engine import Engine
from .engine_mode import EngineMode


class EngineFactory:
    _STRATEGIES: ClassVar[Dict[EngineMode, Type[Engine]]] = {
        EngineMode.MAIN: Engine,
        EngineMode.DRY: DryEngine,
    }

    @classmethod
    def create(
            cls,
            mode: EngineMode,
            har_path: Path,
            output_dir: Path,
            config_path: Optional[Path],
    ) -> Engine:
        engine_cls: Type[Engine] = cls._STRATEGIES[mode]
        return engine_cls(har_path, output_dir, config_path=config_path)
