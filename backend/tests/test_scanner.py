"""Part E/F: app/languages/scanner.py -- registry-key correctness (the
KNOWN HAZARDS item: a mismatched key silently means a language is never
scanned, no error), per-file guards (size skip, parse-timeout abandon), and
edge/symbol aggregation."""

import time
from unittest.mock import patch

from app.ingestion.miner import LANGUAGE_BY_EXT
from app.languages import scanner
from app.languages.base import Symbol
from app.languages.scanner import LANGUAGE_ANALYZERS, extract_structural_edges


def test_registry_keys_match_infer_language_output_for_every_extension():
    """If infer_language returns "typescript" and the registry only has
    "ts", that language silently never gets scanned -- assert the full key
    set line up, not just a couple of examples."""
    produced_languages = {lang for lang in LANGUAGE_BY_EXT.values() if lang != "other"}
    assert produced_languages <= set(LANGUAGE_ANALYZERS)


def test_every_registered_analyzer_language_property_matches_or_is_shared():
    # javascript and typescript deliberately share one instance/identity --
    # everything else's own .language should equal its registry key.
    for key, analyzer in LANGUAGE_ANALYZERS.items():
        if key == "typescript":
            assert analyzer is LANGUAGE_ANALYZERS["javascript"]
        else:
            assert analyzer.language == key


def test_file_over_size_limit_is_skipped(tmp_path):
    big_content = "import os\n" + ("x = 1\n" * 300_000)  # comfortably over MAX_FILE_BYTES
    (tmp_path / "big.py").write_text(big_content)
    (tmp_path / "small.py").write_text("import os\nclass Marker:\n    pass\n")

    result = extract_structural_edges(str(tmp_path))

    # big.py must never have been handed to an analyzer at all -- it
    # contributes no symbols and isn't counted in by_language's file total.
    assert not any(path == "big.py" for path, _symbol in result.symbols)
    assert result.by_language["python"]["files"] == 1
    assert result.symbols == [
        ("small.py", Symbol(name="Marker", kind="class", line=2, exported=True))
    ]


def test_parse_timeout_abandons_a_hanging_file(tmp_path, monkeypatch):
    (tmp_path / "slow.py").write_text("import os\n")

    monkeypatch.setattr(scanner, "_PARSE_TIMEOUT_SECONDS", 0.05)

    def _hang(analyzer, rel_path, repo_root):
        time.sleep(1.0)
        return scanner._FileScanResult(edges=[("unreachable.py", "static")], symbols=[])

    with patch.object(scanner, "_scan_one_file", side_effect=_hang):
        result = extract_structural_edges(str(tmp_path))

    assert result.edges == []  # the hung file was abandoned, not waited on


def test_self_import_is_never_an_edge(tmp_path):
    (tmp_path / "a.py").write_text("import a\n")  # degenerate/self-referential
    result = extract_structural_edges(str(tmp_path))
    assert result.edges == []


def test_edges_are_deduplicated_across_multiple_import_statements(tmp_path):
    (tmp_path / "a.py").write_text("import b\nfrom b import x\n")
    (tmp_path / "b.py").write_text("x = 1\n")
    result = extract_structural_edges(str(tmp_path))
    a_to_b = [e for e in result.edges if e.from_path == "a.py" and e.to_path == "b.py"]
    assert len(a_to_b) == 1


def test_by_language_counts_are_reported(tmp_path):
    (tmp_path / "a.py").write_text("import b\ndef f():\n    pass\n")
    (tmp_path / "b.py").write_text("value = 1\n")
    result = extract_structural_edges(str(tmp_path))
    assert result.by_language["python"]["files"] == 2
    assert result.by_language["python"]["edges"] == 1
    assert result.by_language["python"]["symbols"] == 1  # def f()


def test_symbols_are_paired_with_their_repo_relative_path(tmp_path):
    (tmp_path / "a.py").write_text("class Foo:\n    pass\n")
    result = extract_structural_edges(str(tmp_path))
    assert result.symbols == [("a.py", Symbol(name="Foo", kind="class", line=1, exported=True))]


def test_ignored_directories_are_never_scanned(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text('import "./other";\n')
    (tmp_path / "a.py").write_text("value = 1\n")
    result = extract_structural_edges(str(tmp_path))
    assert result.by_language.get("javascript") is None
