from pathlib import Path
from typing import ClassVar


class HarMaterializer:

    PORT_PLACEHOLDER: ClassVar[str] = "__PORT__"

    def materialize(self, source: Path, destination: Path, port: int) -> Path:
        content: str = source.read_text(encoding="utf-8").replace(self.PORT_PLACEHOLDER, str(port))
        destination.write_text(content, encoding="utf-8")
        return destination
