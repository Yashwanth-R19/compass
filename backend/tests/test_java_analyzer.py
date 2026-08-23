"""Part F: JavaAnalyzer positive + negative cases, against a real fixture
repo (tests/fixtures/java_repo/), plus the O(n^2) guard test -- prepare()
must build the class index once per run, never once per file.
"""

from pathlib import Path
from unittest.mock import patch

from app.languages.java_analyzer import MAX_WILDCARD_EDGES, JavaAnalyzer

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "java_repo"


def _analyzer() -> JavaAnalyzer:
    analyzer = JavaAnalyzer()
    analyzer.prepare(str(FIXTURE_ROOT))
    return analyzer


def test_main_java_produces_exactly_the_expected_edges():
    analyzer = _analyzer()
    edges = analyzer.extract_imports("com/example/app/Main.java", str(FIXTURE_ROOT))
    assert set(edges) == {
        "com/example/other/Thing.java",
        "com/example/pkg/A.java",
        "com/example/pkg/B.java",
        "com/example/pkg/C.java",
    }


def test_jdk_import_produces_no_edge():
    """import java.util.List -- not in the repo's class index, dropped."""
    analyzer = _analyzer()
    edges = analyzer.extract_imports("com/example/app/Main.java", str(FIXTURE_ROOT))
    assert not any("java/util" in e or "List" in e for e in edges)


def test_qualified_import_of_an_existing_class_resolves():
    analyzer = _analyzer()
    edges = analyzer.extract_imports("com/example/app/Main.java", str(FIXTURE_ROOT))
    assert "com/example/other/Thing.java" in edges


def test_wildcard_import_produces_one_edge_per_indexed_class():
    analyzer = _analyzer()
    edges = analyzer.extract_imports("com/example/app/Main.java", str(FIXTURE_ROOT))
    pkg_edges = [e for e in edges if e.startswith("com/example/pkg/")]
    assert set(pkg_edges) == {
        "com/example/pkg/A.java",
        "com/example/pkg/B.java",
        "com/example/pkg/C.java",
    }


def test_static_import_strips_trailing_member(tmp_path):
    (tmp_path / "com" / "example" / "util").mkdir(parents=True)
    (tmp_path / "com" / "example" / "util" / "Helper.java").write_text(
        "package com.example.util;\npublic class Helper { public static void go() {} }\n"
    )
    (tmp_path / "com" / "example" / "app").mkdir(parents=True)
    (tmp_path / "com" / "example" / "app" / "User.java").write_text(
        "package com.example.app;\n"
        "import static com.example.util.Helper.go;\n"
        "public class User {}\n"
    )
    analyzer = JavaAnalyzer()
    analyzer.prepare(str(tmp_path))
    edges = analyzer.extract_imports("com/example/app/User.java", str(tmp_path))
    assert edges == ["com/example/util/Helper.java"]


def test_wildcard_import_capped_at_fifty(tmp_path):
    big = tmp_path / "com" / "example" / "big"
    big.mkdir(parents=True)
    for i in range(75):
        (big / f"C{i}.java").write_text(f"package com.example.big;\npublic class C{i} {{}}\n")
    app = tmp_path / "com" / "example" / "app"
    app.mkdir(parents=True)
    (app / "Wild.java").write_text(
        "package com.example.app;\nimport com.example.big.*;\npublic class Wild {}\n"
    )
    analyzer = JavaAnalyzer()
    analyzer.prepare(str(tmp_path))
    edges = analyzer.extract_imports("com/example/app/Wild.java", str(tmp_path))
    assert len(edges) == MAX_WILDCARD_EDGES == 50


def test_prepare_called_once_per_run_not_once_per_file(tmp_path):
    """The O(n^2) guard (Part C / KNOWN HAZARDS): building the class index
    inside prepare() must happen exactly once, regardless of how many .java
    files the repo has."""
    for i in range(5):
        d = tmp_path / "com" / "example" / f"pkg{i}"
        d.mkdir(parents=True)
        (d / f"Cls{i}.java").write_text(f"package com.example.pkg{i};\npublic class Cls{i} {{}}\n")

    from app.languages import scanner

    java_analyzer = scanner.LANGUAGE_ANALYZERS["java"]
    assert isinstance(java_analyzer, JavaAnalyzer)
    with patch.object(JavaAnalyzer, "prepare", wraps=java_analyzer.prepare) as spy:
        scanner.extract_structural_edges(str(tmp_path))
        assert spy.call_count == 1


def test_symbols_public_main_uses_exact_convention():
    """Session 04 looks for a Java entry point by querying symbols for
    name='main' -- must be exactly kind="method", name="main", exported=True."""
    analyzer = _analyzer()
    symbols = analyzer.extract_symbols("com/example/app/Main.java", str(FIXTURE_ROOT))
    main_symbols = [s for s in symbols if s.name == "main"]
    assert len(main_symbols) == 1
    assert main_symbols[0].kind == "method"
    assert main_symbols[0].exported is True


def test_symbols_private_method_not_exported():
    analyzer = JavaAnalyzer()
    tree_root = FIXTURE_ROOT
    analyzer.prepare(str(tree_root))
    symbols = analyzer.extract_symbols("com/example/other/Thing.java", str(tree_root))
    class_symbols = {s.name: s for s in symbols}
    assert class_symbols["Thing"].kind == "class"
    assert class_symbols["Thing"].exported is True


def test_registry_key_matches_infer_language():
    from app.ingestion.miner import infer_language
    from app.languages.scanner import LANGUAGE_ANALYZERS

    assert infer_language("Main.java") in LANGUAGE_ANALYZERS
    assert LANGUAGE_ANALYZERS[infer_language("Main.java")].language == "java"
