import json
from pathlib import Path

import pytest

from nimea_robot.api import Contexto

DEMO = Path(__file__).parents[1] / "nimea_robot" / "demo.json"


@pytest.fixture
def contexto() -> Contexto:
    return Contexto.desde_dict(json.loads(DEMO.read_text(encoding="utf-8")))
