from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

def test_reproducibility_files_exist():
    assert (ROOT / "requirements.lock").is_file()
    assert (ROOT / "src/poi_mpp/__init__.py").is_file()
    makefile = (ROOT / "Makefile").read_text()
    for target in ("test-unit:", "test-integration:", "test-contracts:", "test-all:", "reproduce:"):
        assert target in makefile


def test_reproducible_environment_contract_is_exact():
    pyproject = (ROOT / "pyproject.toml").read_text()
    lock = (ROOT / "requirements.lock").read_text()
    environment_guide = (ROOT / "envs/README.md").read_text()

    assert 'requires = ["setuptools==82.0.1"]' in pyproject
    assert 'requires-python = "==3.11.*"' in pyproject
    assert "setuptools==82.0.1" in lock
    assert "Python == 3.11.*" in environment_guide
    assert "Dependencies: `../requirements.lock`" in environment_guide
