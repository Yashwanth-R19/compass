"""Part F: JavaScriptAnalyzer positive + negative cases, against a real
fixture repo (tests/fixtures/javascript_repo/). The negative cases are what
stop this analyzer drifting toward guessing (plan/RULES.md sec 8) -- a bare
package specifier and a template-literal dynamic import must NEVER produce
an edge, no matter how tempting a "best guess" would be.
"""

import json
from pathlib import Path

from app.languages.javascript_analyzer import JavaScriptAnalyzer

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "javascript_repo"


def _analyzer() -> JavaScriptAnalyzer:
    analyzer = JavaScriptAnalyzer()
    analyzer.prepare(str(FIXTURE_ROOT))
    return analyzer


def test_main_ts_produces_exactly_the_expected_edges():
    """src/main.ts exercises every resolution case in one file: a bare
    package import (dropped), a dynamic import with a template-literal
    argument (dropped), an extension-swapped relative import, a
    directory-index relative import, and a tsconfig path-alias import."""
    analyzer = _analyzer()
    edges = analyzer.extract_imports("src/main.ts", str(FIXTURE_ROOT))
    assert set(edges) == {"src/foo.ts", "src/bar/index.tsx", "src/aliased.ts"}


def test_bare_package_specifier_produces_no_edge():
    analyzer = _analyzer()
    edges = analyzer.extract_imports("src/main.ts", str(FIXTURE_ROOT))
    assert not any("react" in e for e in edges)


def test_dynamic_import_with_template_literal_produces_no_edge():
    analyzer = _analyzer()
    edge_pairs = analyzer.extract_import_edges("src/main.ts", str(FIXTURE_ROOT))
    dynamic_targets = [target for target, kind in edge_pairs if kind == "dynamic"]
    assert dynamic_targets == []  # only the (dropped) template-literal call exists in this file


def test_dynamic_import_with_string_literal_is_tagged_dynamic(tmp_path):
    (tmp_path / "a.ts").write_text('const f = () => import("./b");\n')
    (tmp_path / "b.ts").write_text("export const b = 1;\n")
    analyzer = JavaScriptAnalyzer()
    analyzer.prepare(str(tmp_path))
    edge_pairs = analyzer.extract_import_edges("a.ts", str(tmp_path))
    assert edge_pairs == [("b.ts", "dynamic")]


def test_extension_swap_js_to_ts():
    """./foo.js is imported, but only src/foo.ts exists on disk."""
    analyzer = _analyzer()
    edges = analyzer.extract_imports("src/main.ts", str(FIXTURE_ROOT))
    assert "src/foo.ts" in edges


def test_directory_index_resolution():
    """./bar is imported, and only src/bar/index.tsx exists (no bar.ts)."""
    analyzer = _analyzer()
    edges = analyzer.extract_imports("src/main.ts", str(FIXTURE_ROOT))
    assert "src/bar/index.tsx" in edges


def test_tsconfig_path_alias_resolves():
    analyzer = _analyzer()
    edges = analyzer.extract_imports("src/main.ts", str(FIXTURE_ROOT))
    assert "src/aliased.ts" in edges


def test_tsconfig_with_comments_and_trailing_comma_still_parses():
    """The fixture's tsconfig.json (tests/fixtures/javascript_repo/tsconfig.json)
    has a // comment and a trailing comma after the paths entry -- real
    tsconfig files routinely do. Discovered directly (not just via the
    alias resolving end-to-end in test_tsconfig_path_alias_resolves) so a
    regression here fails with a precise message instead of a vague
    "edge missing"."""
    from app.languages.javascript_analyzer import _discover_alias_configs

    configs = _discover_alias_configs(str(FIXTURE_ROOT))
    assert configs[""].paths == {"@app/*": ["src/*"]}
    assert configs[""].base_dir == ""


def test_jsonc_comment_or_string_containing_slash_slash_does_not_break_parsing(tmp_path):
    """A string value that happens to contain "//" (e.g. a URL) must not be
    mistaken for the start of a line comment."""
    from app.languages.javascript_analyzer import _load_jsonc

    (tmp_path / "tsconfig.json").write_text(
        '{ "compilerOptions": { "baseUrl": "https://example.com", '
        '"paths": { "@app/*": ["src/*"] } } }'
    )
    data = _load_jsonc(tmp_path / "tsconfig.json")
    assert data["compilerOptions"]["baseUrl"] == "https://example.com"


def test_unresolvable_bare_specifier_in_isolated_fixture_is_dropped(tmp_path):
    (tmp_path / "a.ts").write_text('import lodash from "lodash";\n')
    analyzer = JavaScriptAnalyzer()
    analyzer.prepare(str(tmp_path))
    assert analyzer.extract_imports("a.ts", str(tmp_path)) == []


def test_nearest_tsconfig_wins_over_root_in_a_monorepo(tmp_path):
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "x.ts").write_text("export const x = 1;\n")
    (tmp_path / "packages" / "app" / "pkg-shared").mkdir(parents=True)
    (tmp_path / "packages" / "app" / "pkg-shared" / "x.ts").write_text("export const x = 2;\n")
    (tmp_path / "packages" / "app" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "app" / "src" / "main.ts").write_text(
        'import { x } from "@shared/x";\n'
    )
    (tmp_path / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@shared/*": ["shared/*"]}}})
    )
    (tmp_path / "packages" / "app" / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"paths": {"@shared/*": ["pkg-shared/*"]}}})
    )

    analyzer = JavaScriptAnalyzer()
    analyzer.prepare(str(tmp_path))
    edges = analyzer.extract_imports("packages/app/src/main.ts", str(tmp_path))
    assert edges == ["packages/app/pkg-shared/x.ts"]


def test_symbols_extracted_with_export_and_kind():
    analyzer = _analyzer()
    symbols = analyzer.extract_symbols("src/main.ts", str(FIXTURE_ROOT))
    by_name = {s.name: s for s in symbols}
    assert by_name["useAll"].kind == "function"
    assert by_name["useAll"].exported is True
    assert by_name["dyn"].kind == "function"  # arrow-function lexical_declaration
    assert by_name["dyn"].exported is False


def test_symbols_registry_key_matches_infer_language():
    """The registry key MUST match infer_language's output exactly, or this
    analyzer silently never runs for that language (KNOWN HAZARDS)."""
    from app.ingestion.miner import infer_language
    from app.languages.scanner import LANGUAGE_ANALYZERS

    assert infer_language("x.ts") in LANGUAGE_ANALYZERS
    assert infer_language("x.tsx") in LANGUAGE_ANALYZERS
    assert infer_language("x.js") in LANGUAGE_ANALYZERS
    assert infer_language("x.jsx") in LANGUAGE_ANALYZERS
