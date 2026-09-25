"""L'API ne charge aucune bibliothèque de ML (décision 11, ADR 0035).

Le chemin d'une requête ne sert que des résultats déjà calculés : numpy, pandas,
scipy et statsmodels n'ont rien à y faire, et l'image API ne les installe pas. Le
test importe l'application dans un processus neuf et inspecte ce qui a été chargé —
un `import` glissé par mégarde dans `serving.py` ou dans une façade le ferait échouer.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ML_LIBRARIES = ("numpy", "pandas", "scipy", "statsmodels")


def test_importing_the_api_loads_no_ml_library() -> None:
    probe = (
        "import json, sys, app.main; "
        f"print(json.dumps([m for m in {list(ML_LIBRARIES)!r} if m in sys.modules]))"
    )
    result = subprocess.run(  # noqa: S603 - commande fixe, aucune entrée externe
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    assert loaded == [], f"l'API charge des bibliothèques de ML : {loaded}"
