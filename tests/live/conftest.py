"""Guardie per i test live: eseguono richieste reali contro Normattiva.it.

Tre difese indipendenti, ognuna sufficiente da sola a impedire un'esecuzione
accidentale — pattern ripreso dai due progetti gemelli (mcp-bdm,
italgiure-web-mcp):

1. `addopts = "-m 'not live'"` in pyproject.toml: pytest, di default, non
   raccoglie nemmeno questi test.
2. La variabile d'ambiente NORMATTIVA_LIVE_TESTS=1, controllata qui sotto.
3. Il "cinturino": questi test si rifiutano di girare dentro un git hook
   (rilevato da GIT_INDEX_FILE nell'ambiente). Il pre-commit di questo
   progetto non li esegue mai — ma se qualcuno impostasse la variabile
   d'ambiente nella propria shell per un test manuale, il prossimo commit
   erediterebbe quella variabile e spenderebbe richieste reali a sua insaputa.
"""

import os

import pytest


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "live" not in {marker.name for marker in item.iter_markers()}:
        return

    if os.environ.get("GIT_INDEX_FILE"):
        pytest.skip(
            "test live rifiutato dentro un git hook (GIT_INDEX_FILE presente): "
            "esportare NORMATTIVA_LIVE_TESTS=1 in un terminale, mai in un hook"
        )

    if os.environ.get("NORMATTIVA_LIVE_TESTS") != "1":
        pytest.skip(
            "test live opt-in: richiede NORMATTIVA_LIVE_TESTS=1 "
            "(esegue richieste reali contro Normattiva.it)"
        )
