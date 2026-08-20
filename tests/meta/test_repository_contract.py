from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

def test_reproducibility_files_exist():
    assert (ROOT / "requirements.lock").is_file()
    assert (ROOT / "src/poi_mpp/__init__.py").is_file()
    makefile = (ROOT / "Makefile").read_text()
    for target in ("test-unit:", "test-integration:", "test-contracts:", "test-all:", "reproduce:"):
        assert target in makefile
