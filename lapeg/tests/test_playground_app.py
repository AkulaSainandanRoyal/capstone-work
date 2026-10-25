"""The playground renders without a fork (headless Streamlit), with no exceptions and no network calls."""

from streamlit.testing.v1 import AppTest

from lapeg import PROJECT_ROOT

APP = str(PROJECT_ROOT / "lapeg" / "app" / "playground.py")


def test_playground_renders_without_a_fork() -> None:
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "LAPEG playground"
    assert any("Start a fork" in i.value for i in at.info)       # interactive tabs wait for a fork
    assert at.radio[0].options[0].startswith("Latest block")      # block presets are listed
