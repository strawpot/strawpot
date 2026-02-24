"""Tests for SkillsLoader (pool directory scanner) and SkillFile."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from core.skills.loader import SkillsLoader, _extract_description, _extract_tags, _extract_title
from core.skills.types import SkillFile, SkillPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pool_tree(tmp_path: Path) -> tuple[SkillPool, dict[str, Path]]:
    """Create a project pool with three skill modules."""
    pool_path = tmp_path / "skills"
    pool_path.mkdir()

    modules: dict[str, Path] = {}

    # Module 1: commit-conventions — has README.md with frontmatter description
    m1 = pool_path / "commit-conventions"
    m1.mkdir()
    (m1 / "README.md").write_text(
        textwrap.dedent("""\
            ---
            description: Commit message style guide
            tags: [git, commits]
            ---

            # Commit Conventions

            Use conventional commits.
        """)
    )
    modules["commit-conventions"] = m1

    # Module 2: typescript-patterns — has a guide.md and sub-dir (no frontmatter)
    m2 = pool_path / "typescript-patterns"
    m2.mkdir()
    (m2 / "guide.md").write_text("# TypeScript Patterns\n\nPrefer const over let.\n")
    sub = m2 / "snippets"
    sub.mkdir()
    (sub / "usage.md").write_text("## Examples\n\nSome examples.\n")
    modules["typescript-patterns"] = m2

    # Module 3: empty-module — no .md files
    m3 = pool_path / "empty-module"
    m3.mkdir()
    modules["empty-module"] = m3

    pool = SkillPool(path=pool_path, scope="project")
    return pool, modules


# ---------------------------------------------------------------------------
# _extract_title helpers
# ---------------------------------------------------------------------------


def test_extract_title_h1():
    assert _extract_title("# Hello World\n\nBody.", "fallback") == "Hello World"


def test_extract_title_h2():
    assert _extract_title("## My Skill\n\nBody.", "fallback") == "My Skill"


def test_extract_title_strips_frontmatter():
    content = "---\ntags: [a]\n---\n\n# Real Title\n\nBody."
    assert _extract_title(content, "fallback") == "Real Title"


def test_extract_title_fallback():
    assert _extract_title("No heading here.", "my-file") == "my-file"


# ---------------------------------------------------------------------------
# _extract_description helper
# ---------------------------------------------------------------------------


def test_extract_description_present():
    content = "---\ndescription: A handy guide\n---\n\n# X"
    assert _extract_description(content) == "A handy guide"


def test_extract_description_quoted():
    content = '---\ndescription: "Quoted description"\n---\n\n# X'
    assert _extract_description(content) == "Quoted description"


def test_extract_description_absent():
    assert _extract_description("# No frontmatter") == ""


# ---------------------------------------------------------------------------
# _extract_tags helper
# ---------------------------------------------------------------------------


def test_extract_tags_present():
    content = "---\ntags: [a, b, c]\n---\n\n# X"
    assert _extract_tags(content) == ["a", "b", "c"]


def test_extract_tags_absent():
    assert _extract_tags("# No frontmatter") == []


def test_extract_tags_empty_list():
    assert _extract_tags("---\ntags: []\n---\n# X") == []


# ---------------------------------------------------------------------------
# SkillsLoader.list_modules
# ---------------------------------------------------------------------------


def test_list_modules_returns_directories(pool_tree):
    pool, modules = pool_tree
    result = SkillsLoader.list_modules(pool)
    names = [d.name for d in result]
    assert "commit-conventions" in names
    assert "typescript-patterns" in names
    assert "empty-module" in names


def test_list_modules_sorted(pool_tree):
    pool, _ = pool_tree
    result = SkillsLoader.list_modules(pool)
    names = [d.name for d in result]
    assert names == sorted(names)


def test_list_modules_empty_pool(tmp_path: Path):
    pool_path = tmp_path / "skills"
    pool_path.mkdir()
    pool = SkillPool(path=pool_path, scope="project")
    assert SkillsLoader.list_modules(pool) == []


def test_list_modules_nonexistent_pool(tmp_path: Path):
    pool = SkillPool(path=tmp_path / "nonexistent", scope="project")
    assert SkillsLoader.list_modules(pool) == []


def test_list_modules_skips_files(tmp_path: Path):
    pool_path = tmp_path / "skills"
    pool_path.mkdir()
    (pool_path / "not-a-module.md").write_text("# File")
    (pool_path / "valid-module").mkdir()
    pool = SkillPool(path=pool_path, scope="project")
    result = SkillsLoader.list_modules(pool)
    assert len(result) == 1
    assert result[0].name == "valid-module"


def test_list_modules_skips_hidden_dirs(tmp_path: Path):
    pool_path = tmp_path / "skills"
    pool_path.mkdir()
    (pool_path / ".hidden").mkdir()
    (pool_path / "visible-module").mkdir()
    pool = SkillPool(path=pool_path, scope="project")
    result = SkillsLoader.list_modules(pool)
    names = [d.name for d in result]
    assert ".hidden" not in names
    assert "visible-module" in names


# ---------------------------------------------------------------------------
# SkillsLoader.module_description
# ---------------------------------------------------------------------------


def test_module_description_from_readme_frontmatter(pool_tree):
    _, modules = pool_tree
    desc = SkillsLoader.module_description(modules["commit-conventions"])
    assert desc == "Commit message style guide"


def test_module_description_from_readme_heading(tmp_path: Path):
    mod = tmp_path / "my-module"
    mod.mkdir()
    (mod / "README.md").write_text("# My Module\n\nContent.\n")
    assert SkillsLoader.module_description(mod) == "My Module"


def test_module_description_from_first_md_heading(pool_tree):
    _, modules = pool_tree
    # typescript-patterns has no frontmatter description, falls back to heading
    desc = SkillsLoader.module_description(modules["typescript-patterns"])
    assert desc == "TypeScript Patterns"


def test_module_description_empty_when_no_md(pool_tree):
    _, modules = pool_tree
    assert SkillsLoader.module_description(modules["empty-module"]) == ""


# ---------------------------------------------------------------------------
# SkillsLoader.list_files
# ---------------------------------------------------------------------------


def test_list_files_returns_skill_file_objects(pool_tree):
    _, modules = pool_tree
    files = SkillsLoader.list_files(modules["typescript-patterns"])
    assert all(isinstance(f, SkillFile) for f in files)


def test_list_files_sorted(pool_tree):
    _, modules = pool_tree
    files = SkillsLoader.list_files(modules["typescript-patterns"])
    paths = [f.path for f in files]
    assert paths == sorted(paths)


def test_list_files_reads_content(pool_tree):
    _, modules = pool_tree
    files = SkillsLoader.list_files(modules["typescript-patterns"])
    titles = [f.title for f in files]
    assert "TypeScript Patterns" in titles


def test_list_files_populates_tags(pool_tree):
    _, modules = pool_tree
    files = SkillsLoader.list_files(modules["commit-conventions"])
    readme_file = next(f for f in files if f.path.name == "README.md")
    assert "git" in readme_file.tags
    assert "commits" in readme_file.tags


def test_list_files_populates_description(pool_tree):
    _, modules = pool_tree
    files = SkillsLoader.list_files(modules["commit-conventions"])
    readme_file = next(f for f in files if f.path.name == "README.md")
    assert readme_file.description == "Commit message style guide"


def test_list_files_empty_when_no_md(pool_tree):
    _, modules = pool_tree
    assert SkillsLoader.list_files(modules["empty-module"]) == []


def test_list_files_nonexistent_dir(tmp_path: Path):
    assert SkillsLoader.list_files(tmp_path / "nonexistent") == []


def test_list_files_recursive(tmp_path: Path):
    """Files in sub-directories of a module are included."""
    mod = tmp_path / "my-skill"
    mod.mkdir()
    (mod / "guide.md").write_text("# Guide\n")
    sub = mod / "examples"
    sub.mkdir()
    (sub / "snippet.md").write_text("# Snippet\n")
    files = SkillsLoader.list_files(mod)
    names = [f.path.name for f in files]
    assert "guide.md" in names
    assert "snippet.md" in names


# ---------------------------------------------------------------------------
# SkillFile.name property
# ---------------------------------------------------------------------------


def test_skill_file_name_hyphens_to_underscores():
    sf = SkillFile(path=Path("typescript-patterns.md"), title="TypeScript Patterns", content="")
    assert sf.name == "typescript_patterns"


def test_skill_file_name_already_underscored():
    sf = SkillFile(path=Path("commit_style.md"), title="Commit Style", content="")
    assert sf.name == "commit_style"


def test_skill_file_name_lowercase():
    sf = SkillFile(path=Path("MySkill.md"), title="My Skill", content="")
    assert sf.name == "myskill"
