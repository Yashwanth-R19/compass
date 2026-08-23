"""Part D: app/ingestion/manifests.py -- each kind extracts only its named
fields, never the whole file, and a malformed manifest is silently skipped
rather than crashing the structure stage."""

import json
import textwrap

from app.ingestion.manifests import extract_manifests


def test_package_json_extracts_only_named_fields(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "myapp",
                "version": "1.2.3",  # not in the extracted field list
                "main": "index.js",
                "scripts": {"build": "tsc"},
                "dependencies": {"react": "^18.0.0"},
                "devDependencies": {"vitest": "^1.0.0"},
                "private": True,  # not in the extracted field list
            }
        )
    )
    rows = extract_manifests(str(tmp_path))
    assert len(rows) == 1
    assert rows[0].kind == "package_json"
    assert rows[0].path == "package.json"
    assert rows[0].data == {
        "name": "myapp",
        "main": "index.js",
        "scripts": {"build": "tsc"},
        "dependencies": {"react": "^18.0.0"},
        "devDependencies": {"vitest": "^1.0.0"},
    }
    assert "version" not in rows[0].data
    assert "private" not in rows[0].data


def test_malformed_package_json_is_skipped_not_crashed(tmp_path):
    (tmp_path / "package.json").write_text("{not valid json")
    rows = extract_manifests(str(tmp_path))
    assert rows == []


def test_pyproject_toml_extracts_project_and_poetry_fields(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "compass"
            dependencies = ["fastapi"]

            [tool.poetry]
            name = "compass-poetry"
            dependencies = {python = "^3.11"}
            """
        )
    )
    rows = extract_manifests(str(tmp_path))
    assert len(rows) == 1
    assert rows[0].kind == "pyproject"
    assert rows[0].data["name"] == "compass"
    assert rows[0].data["dependencies"] == ["fastapi"]
    assert rows[0].data["poetry"]["name"] == "compass-poetry"


def test_requirements_txt_keeps_raw_lines(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.115\n\nuvicorn\n# a comment\n")
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "requirements"
    assert rows[0].data == {"lines": ["fastapi==0.115", "uvicorn", "# a comment"]}


def test_requirements_dev_variant_filename_is_classified(tmp_path):
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "requirements"
    assert rows[0].path == "requirements-dev.txt"


def test_dockerfile_extracts_cmd_and_entrypoint(tmp_path):
    (tmp_path / "Dockerfile").write_text(
        'FROM python:3.11\nRUN pip install -e .\nENTRYPOINT ["python"]\nCMD ["-m", "app"]\n'
    )
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "dockerfile"
    assert rows[0].data["CMD"] == ['["-m", "app"]']
    assert rows[0].data["ENTRYPOINT"] == ['["python"]']
    assert "RUN" not in rows[0].data


def test_procfile_keeps_every_line(tmp_path):
    (tmp_path / "Procfile").write_text("web: gunicorn app:app\nworker: celery worker\n")
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "procfile"
    assert rows[0].data == {"lines": ["web: gunicorn app:app", "worker: celery worker"]}


def test_pom_xml_extracts_main_class_and_dependencies(tmp_path):
    (tmp_path / "pom.xml").write_text(
        """<project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencies>
            <dependency>
              <groupId>com.example</groupId>
              <artifactId>lib</artifactId>
              <version>1.0</version>
            </dependency>
          </dependencies>
          <properties><mainClass>com.example.Main</mainClass></properties>
        </project>"""
    )
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "pom_xml"
    assert rows[0].data["mainClass"] == "com.example.Main"
    assert rows[0].data["dependencies"] == [
        {"groupId": "com.example", "artifactId": "lib", "version": "1.0"}
    ]


def test_malformed_pom_xml_is_skipped(tmp_path):
    (tmp_path / "pom.xml").write_text("<project><unclosed>")
    assert extract_manifests(str(tmp_path)) == []


def test_build_gradle_extracts_literal_coordinates_only(tmp_path):
    (tmp_path / "build.gradle").write_text(
        "dependencies {\n"
        "  implementation 'com.squareup.okhttp3:okhttp:4.9.0'\n"
        '  testImplementation "junit:junit:4.13.2"\n'
        "  implementation project(':core')\n"  # not a coordinate literal
        "}\n"
    )
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "build_gradle"
    assert rows[0].data["dependencies"] == [
        "com.squareup.okhttp3:okhttp:4.9.0",
        "junit:junit:4.13.2",
    ]


def test_build_gradle_kts_variant_is_classified(tmp_path):
    (tmp_path / "build.gradle.kts").write_text(
        'dependencies { implementation("com.squareup.okhttp3:okhttp:4.9.0") }\n'
    )
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "build_gradle"
    assert rows[0].path == "build.gradle.kts"


def test_setup_py_extracts_trivially_parseable_entry_points(tmp_path):
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='x', entry_points={'console_scripts': ['x=x:main']})\n"
    )
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "setup_py"
    assert rows[0].data == {"entry_points": {"console_scripts": ["x=x:main"]}}


def test_setup_py_with_non_literal_entry_points_extracts_nothing(tmp_path):
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "eps = compute_entry_points()\n"
        "setup(name='x', entry_points=eps)\n"
    )
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "setup_py"
    assert rows[0].data == {}


def test_readme_extracts_heading_and_line_count_not_content(tmp_path):
    (tmp_path / "README.md").write_text("# My Project\n\nSome body text here.\nMore text.\n")
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "readme"
    assert rows[0].data["heading"] == "My Project"
    assert rows[0].data["line_count"] == 4
    assert "Some body text" not in json.dumps(rows[0].data)


def test_license_detects_mit_by_keyword_match(tmp_path):
    (tmp_path / "LICENSE").write_text(
        "MIT License\n\nPermission is hereby granted, free of charge, to any person...\n"
    )
    rows = extract_manifests(str(tmp_path))
    assert rows[0].kind == "license"
    assert rows[0].data == {"spdx_id": "MIT"}


def test_license_unrecognized_text_yields_null_spdx_id(tmp_path):
    (tmp_path / "LICENSE").write_text("All rights reserved. Do not copy.\n")
    rows = extract_manifests(str(tmp_path))
    assert rows[0].data == {"spdx_id": None}


def test_ignored_directories_are_never_walked(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.json").write_text("{}")
    (tmp_path / "package.json").write_text('{"name": "root"}')
    rows = extract_manifests(str(tmp_path))
    assert [r.path for r in rows] == ["package.json"]


def test_monorepo_multiple_manifests_all_extracted(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "root"}')
    (tmp_path / "packages" / "a").mkdir(parents=True)
    (tmp_path / "packages" / "a" / "package.json").write_text('{"name": "a"}')
    rows = extract_manifests(str(tmp_path))
    paths = {r.path for r in rows}
    assert paths == {"package.json", "packages/a/package.json"}
