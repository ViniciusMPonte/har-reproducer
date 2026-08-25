from pathlib import Path
from typing import ClassVar

import pytest

from tests.real.support.real_capture import RealCapture


class RealFixtureConfig:
    CAPTURES_DIR: ClassVar[Path] = Path(__file__).parent / "captures"


class UnimedriopretoCaptureConfig:
    FOLDER_NAME: ClassVar[str] = "autorizador.unimedriopreto.com.br__20260824"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "real_capture: usa dados reais de tests/real/captures/")


@pytest.fixture
def real_captures_dir() -> Path:
    return RealFixtureConfig.CAPTURES_DIR


@pytest.fixture
def unimedriopreto_20260824_capture(real_captures_dir: Path) -> RealCapture:
    base_dir: Path = real_captures_dir / UnimedriopretoCaptureConfig.FOLDER_NAME
    if not base_dir.exists():
        pytest.skip(f"captura real ausente em {base_dir} — rode CaptureImporter para importá-la")
    return RealCapture(base_dir)
