"""Session 10, Part C/G: dependency-manifest parsing
(app/ingestion/manifests.py::extract_declared_dependencies) -- the four
supported formats, and Known Hazard #5 (package-lock.json's three format
versions)."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.ingestion.manifests import extract_declared_dependencies


@pytest.fixture
def repo_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _by_name(rows, name):
    return next(r for r in rows if r.package_name == name)


# ---------------------------------------------------------------------------
# requirements*.txt
# ---------------------------------------------------------------------------


def test_requirements_txt_handles_pins_ranges_extras_and_urls(repo_dir):
    (repo_dir / "requirements.txt").write_text(
        "requests==2.31.0\n"
        "flask>=2.0\n"
        "somepkg[extra1,extra2]==1.2.3\n"
        "-e git+https://github.com/x/y.git#egg=editable-pkg\n"
        "https://example.com/some-package.whl\n"
        "# a comment\n"
        "\n"
    )
    rows, manifest_found = extract_declared_dependencies(str(repo_dir))
    assert manifest_found is True

    names = {r.package_name for r in rows}
    assert names == {"requests", "flask", "somepkg"}
    assert _by_name(rows, "requests").version == "2.31.0"
    assert _by_name(rows, "flask").version is None  # a range, not queryable
    assert _by_name(rows, "somepkg").version == "1.2.3"
    for r in rows:
        assert r.ecosystem == "PyPI"
        assert r.is_direct is True
        assert r.scope == "runtime"


def test_requirements_dev_filename_gets_dev_scope(repo_dir):
    (repo_dir / "requirements-dev.txt").write_text("pytest==8.0.0\n")
    rows, _ = extract_declared_dependencies(str(repo_dir))
    assert _by_name(rows, "pytest").scope == "dev"


def test_requirements_r_include_is_resolved_relative_to_including_file(repo_dir):
    (repo_dir / "base.txt").write_text("requests==2.31.0\n")
    (repo_dir / "requirements.txt").write_text("-r base.txt\nflask==2.0.0\n")
    rows, _ = extract_declared_dependencies(str(repo_dir))
    names = {r.package_name for r in rows}
    assert "requests" in names
    assert "flask" in names


def test_requirements_r_include_cycle_does_not_infinite_loop(repo_dir):
    (repo_dir / "a.txt").write_text("-r b.txt\nfoo==1.0.0\n")
    (repo_dir / "b.txt").write_text("-r a.txt\nbar==1.0.0\n")
    # Renaming one of these to match the requirements* glob so the walk
    # actually picks it up as an entry point.
    (repo_dir / "requirements.txt").write_text("-r a.txt\n")
    rows, _ = extract_declared_dependencies(str(repo_dir))
    names = {r.package_name for r in rows}
    assert names == {"foo", "bar"}


# ---------------------------------------------------------------------------
# pyproject.toml [project.dependencies]
# ---------------------------------------------------------------------------


def test_pyproject_project_dependencies_parsed(repo_dir):
    (repo_dir / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["requests==2.31.0", "flask>=2.0", '
        "\"typing-extensions; python_version < '3.10'\"]\n"
    )
    rows, manifest_found = extract_declared_dependencies(str(repo_dir))
    assert manifest_found is True
    names = {r.package_name for r in rows}
    assert names == {"requests", "flask", "typing-extensions"}
    assert _by_name(rows, "requests").version == "2.31.0"
    assert _by_name(rows, "flask").version is None
    assert all(r.ecosystem == "PyPI" and r.is_direct for r in rows)


def test_pyproject_without_project_dependencies_yields_nothing_but_manifest_found(repo_dir):
    (repo_dir / "pyproject.toml").write_text('[project]\nname = "x"\n')
    rows, manifest_found = extract_declared_dependencies(str(repo_dir))
    assert rows == []
    assert manifest_found is True


# ---------------------------------------------------------------------------
# package-lock.json -- Known Hazard #5 (v1 vs v2/v3)
# ---------------------------------------------------------------------------


def test_package_lock_v3_packages_shape(repo_dir):
    lock = {
        "name": "app",
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "app", "dependencies": {"left-pad": "^1.0.0"}},
            "node_modules/left-pad": {"version": "1.3.0"},
            "node_modules/left-pad/node_modules/nested-dep": {"version": "0.1.0", "dev": True},
        },
    }
    (repo_dir / "package-lock.json").write_text(json.dumps(lock))
    rows, manifest_found = extract_declared_dependencies(str(repo_dir))
    assert manifest_found is True

    left_pad = _by_name(rows, "left-pad")
    assert left_pad.version == "1.3.0"
    assert left_pad.is_direct is True
    assert left_pad.ecosystem == "npm"

    nested = _by_name(rows, "nested-dep")
    assert nested.is_direct is False
    assert nested.scope == "dev"


def test_package_lock_v1_dependencies_shape(repo_dir):
    lock = {
        "name": "app",
        "lockfileVersion": 1,
        "dependencies": {
            "left-pad": {
                "version": "1.3.0",
                "dependencies": {"nested-dep": {"version": "0.1.0", "dev": True}},
            }
        },
    }
    (repo_dir / "package-lock.json").write_text(json.dumps(lock))
    rows, manifest_found = extract_declared_dependencies(str(repo_dir))
    assert manifest_found is True

    left_pad = _by_name(rows, "left-pad")
    assert left_pad.is_direct is True
    nested = _by_name(rows, "nested-dep")
    assert nested.is_direct is False


def test_package_lock_unrecognized_shape_skips_without_crashing(repo_dir):
    (repo_dir / "package-lock.json").write_text(json.dumps({"lockfileVersion": 99}))
    rows, manifest_found = extract_declared_dependencies(str(repo_dir))
    assert rows == []
    assert manifest_found is True  # the file was present, just unparseable


# ---------------------------------------------------------------------------
# pom.xml
# ---------------------------------------------------------------------------


_POM_TEMPLATE = """<project>
  <properties>
    <junit.version>4.13.2</junit.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.example</groupId>
      <artifactId>lib-a</artifactId>
      <version>1.2.3</version>
    </dependency>
    <dependency>
      <groupId>junit</groupId>
      <artifactId>junit</artifactId>
      <version>${junit.version}</version>
      <scope>test</scope>
    </dependency>
    <dependency>
      <groupId>org.example</groupId>
      <artifactId>unresolvable</artifactId>
      <version>${undefined.property}</version>
    </dependency>
  </dependencies>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.example</groupId>
        <artifactId>managed-only</artifactId>
        <version>9.9.9</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>
"""


def test_pom_xml_resolves_properties_and_skips_unresolvable(repo_dir):
    (repo_dir / "pom.xml").write_text(_POM_TEMPLATE)
    rows, manifest_found = extract_declared_dependencies(str(repo_dir))
    assert manifest_found is True

    names = {r.package_name for r in rows}
    assert "org.example:lib-a" in names
    assert "junit:junit" in names
    # unresolvable version -> skipped entirely, never guessed at
    assert "org.example:unresolvable" not in names
    # dependencyManagement (not top-level <dependencies>) -> never included
    assert "org.example:managed-only" not in names

    junit = _by_name(rows, "junit:junit")
    assert junit.version == "4.13.2"
    assert junit.scope == "test"

    lib_a = _by_name(rows, "org.example:lib-a")
    assert lib_a.ecosystem == "Maven"
    assert lib_a.is_direct is True
    assert lib_a.scope == "runtime"


# ---------------------------------------------------------------------------
# "no supported manifest" honesty
# ---------------------------------------------------------------------------


def test_no_supported_manifest_present_at_all(repo_dir):
    (repo_dir / "README.md").write_text("hello\n")
    rows, manifest_found = extract_declared_dependencies(str(repo_dir))
    assert rows == []
    assert manifest_found is False


def test_ignore_dirs_are_respected(repo_dir):
    nm = repo_dir / "node_modules" / "some-dep"
    os.makedirs(nm)
    (nm / "package-lock.json").write_text(json.dumps({"packages": {}}))
    rows, manifest_found = extract_declared_dependencies(str(repo_dir))
    assert rows == []
    assert manifest_found is False
