"""Tests for strawpot.context."""

import pytest

from strawpot.context import (
    build_prompt,
    read_role_description,
    read_skill_description,
    validate_frontmatter_slug,
)


def _write_skill(base, slug, body):
    d = base / "skills" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {slug}\ndescription: test\n---\n{body}\n"
    )
    return str(d)


def _write_role(base, slug, body):
    d = base / "roles" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "ROLE.md").write_text(
        f"---\nname: {slug}\ndescription: test\n---\n{body}\n"
    )
    return str(d)


def test_role_no_dependencies(tmp_path):
    path = _write_role(tmp_path, "solo", "You are a solo agent.")

    resolved = {
        "slug": "solo",
        "kind": "role",
        "version": "1.0.0",
        "path": path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(resolved)
    assert result == "## Role: solo\n\nYou are a solo agent."


def test_role_with_skill_dependencies(tmp_path):
    skill1_path = _write_skill(tmp_path, "git-workflow", "Use git flow.")
    skill2_path = _write_skill(tmp_path, "code-review", "Review carefully.")
    role_path = _write_role(tmp_path, "implementer", "You implement things.")

    resolved = {
        "slug": "implementer",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [
            {
                "slug": "git-workflow",
                "kind": "skill",
                "version": "1.0.0",
                "path": skill1_path,
                "source": "local",
            },
            {
                "slug": "code-review",
                "kind": "skill",
                "version": "1.0.0",
                "path": skill2_path,
                "source": "local",
            },
        ],
    }

    result = build_prompt(resolved)
    assert result == (
        "## Skill: git-workflow\n\nUse git flow."
        "\n---\n\n"
        "## Skill: code-review\n\nReview carefully."
        "\n---\n\n"
        "## Role: implementer\n\nYou implement things."
    )


def test_role_dependency_includes_role(tmp_path):
    """A role can depend on another role."""
    dep_role_path = _write_role(tmp_path, "base-reviewer", "Review basics.")
    root_path = _write_role(tmp_path, "senior-reviewer", "Senior review.")

    resolved = {
        "slug": "senior-reviewer",
        "kind": "role",
        "version": "1.0.0",
        "path": root_path,
        "source": "local",
        "dependencies": [
            {
                "slug": "base-reviewer",
                "kind": "role",
                "version": "1.0.0",
                "path": dep_role_path,
                "source": "local",
            },
        ],
    }

    result = build_prompt(resolved)
    assert result == (
        "## Role: base-reviewer\n\nReview basics."
        "\n---\n\n"
        "## Role: senior-reviewer\n\nSenior review."
    )


def test_frontmatter_stripped(tmp_path):
    """Frontmatter is stripped, only the body is included."""
    d = tmp_path / "roles" / "complex"
    d.mkdir(parents=True)
    (d / "ROLE.md").write_text(
        "---\n"
        "name: complex\n"
        "description: test\n"
        "metadata:\n"
        "  strawpot:\n"
        "    dependencies:\n"
        "      skills:\n"
        "        - something\n"
        "---\n"
        "# Complex Role\n\n"
        "Body content here.\n"
    )

    resolved = {
        "slug": "complex",
        "kind": "role",
        "version": "1.0.0",
        "path": str(d),
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(resolved)
    assert "---\nname:" not in result
    assert "metadata:" not in result
    assert "# Complex Role" in result
    assert "Body content here." in result


def test_body_whitespace_stripped(tmp_path):
    """Leading/trailing whitespace in body is stripped."""
    d = tmp_path / "skills" / "ws"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: ws\ndescription: test\n---\n\n\n  Body  \n\n\n"
    )

    role_path = _write_role(tmp_path, "r", "Role.")

    resolved = {
        "slug": "r",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [
            {
                "slug": "ws",
                "kind": "skill",
                "version": "1.0.0",
                "path": str(d),
                "source": "local",
            },
        ],
    }

    result = build_prompt(resolved)
    assert result.startswith("## Skill: ws\n\nBody")


# ---------------------------------------------------------------------------
# Delegation section
# ---------------------------------------------------------------------------


def test_delegation_section_appended(tmp_path):
    """Delegation section is appended when delegatable_roles is provided."""
    role_path = _write_role(tmp_path, "orchestrator", "You orchestrate.")

    resolved = {
        "slug": "orchestrator",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(
        resolved,
        delegatable_roles=[
            ("backend-engineer", "Handles backend API implementation"),
            ("test-writer", "Writes and maintains test suites"),
        ],
    )

    assert "## Role: orchestrator\n\nYou orchestrate." in result
    assert "\n---\n\n## Delegation" in result
    assert "- **backend-engineer**: Handles backend API implementation" in result
    assert "- **test-writer**: Writes and maintains test suites" in result
    assert "skills/denden/SKILL.md" in result
    assert "ONLY way to delegate" in result


def test_delegation_with_dependencies(tmp_path):
    """Delegation section comes after role body, after dependencies."""
    skill_path = _write_skill(tmp_path, "git-workflow", "Use git flow.")
    role_path = _write_role(tmp_path, "team-lead", "You lead the team.")

    resolved = {
        "slug": "team-lead",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [
            {
                "slug": "git-workflow",
                "kind": "skill",
                "version": "1.0.0",
                "path": skill_path,
                "source": "local",
            },
        ],
    }

    result = build_prompt(
        resolved,
        delegatable_roles=[("implementer", "Writes code")],
    )

    skill_pos = result.index("## Skill: git-workflow")
    role_pos = result.index("## Role: team-lead")
    delegation_pos = result.index("## Delegation")
    assert skill_pos < role_pos < delegation_pos


def test_no_delegation_when_none(tmp_path):
    """No delegation section when delegatable_roles is None."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    resolved = {
        "slug": "worker",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(resolved, delegatable_roles=None)
    assert "Delegation" not in result


def test_no_delegation_when_empty_list(tmp_path):
    """No delegation section when delegatable_roles is empty."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    resolved = {
        "slug": "worker",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(resolved, delegatable_roles=[])
    assert "Delegation" not in result


def test_delegation_single_role(tmp_path):
    """Delegation section works with a single role."""
    role_path = _write_role(tmp_path, "lead", "You lead.")

    resolved = {
        "slug": "lead",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(
        resolved,
        delegatable_roles=[("fixer", "Fixes bugs and issues")],
    )

    assert "- **fixer**: Fixes bugs and issues" in result
    assert result.count("- **") == 1


def test_delegation_section_exact_format(tmp_path):
    """Delegation section matches the DESIGN.md format exactly."""
    role_path = _write_role(tmp_path, "orch", "Orchestrate.")

    resolved = {
        "slug": "orch",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(
        resolved,
        delegatable_roles=[
            ("backend-engineer", "Handles backend API implementation"),
            ("test-writer", "Writes and maintains test suites"),
        ],
    )

    expected_delegation = (
        "## Delegation\n"
        "\n"
        "You can delegate tasks to the following roles:\n"
        "- **backend-engineer**: Handles backend API implementation\n"
        "- **test-writer**: Writes and maintains test suites\n"
        "\n"
        "Each role is described in `roles/<role-name>/ROLE.md`. Read the ROLE.md\n"
        "file to learn more about the role before delegating.\n"
        "\n"
        "To delegate, read `skills/denden/SKILL.md` and use the `delegate` "
        "command documented there. This is the ONLY way to delegate work. "
        "Never attempt tasks yourself — always delegate via the denden skill."
    )

    assert result.endswith(expected_delegation)


# ---------------------------------------------------------------------------
# Requester section
# ---------------------------------------------------------------------------


def test_requester_section_appended(tmp_path):
    """Requester section is appended when requester_role is provided."""
    role_path = _write_role(tmp_path, "implementer", "You implement.")

    resolved = {
        "slug": "implementer",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(resolved, requester_role="team-lead")

    assert "\n---\n\n## Requester" in result
    assert "**team-lead**" in result
    assert "denden" in result


def test_requester_after_delegation(tmp_path):
    """Requester section comes after delegation section."""
    role_path = _write_role(tmp_path, "lead", "You lead.")

    resolved = {
        "slug": "lead",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(
        resolved,
        delegatable_roles=[("fixer", "Fixes bugs")],
        requester_role="orchestrator",
    )

    delegation_pos = result.index("## Delegation")
    requester_pos = result.index("## Requester")
    assert delegation_pos < requester_pos


def test_no_requester_when_none(tmp_path):
    """No requester section when requester_role is None."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    resolved = {
        "slug": "worker",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(resolved, requester_role=None)
    assert "Requester" not in result


# ---------------------------------------------------------------------------
# read_role_description
# ---------------------------------------------------------------------------


def test_read_role_description(tmp_path):
    """read_role_description extracts description from ROLE.md frontmatter."""
    d = tmp_path / "roles" / "implementer"
    d.mkdir(parents=True)
    (d / "ROLE.md").write_text(
        "---\nname: implementer\ndescription: Writes code to implement features\n---\nBody.\n"
    )

    assert read_role_description(str(d)) == "Writes code to implement features"


def test_read_role_description_missing(tmp_path):
    """read_role_description returns empty string if no description."""
    d = tmp_path / "roles" / "minimal"
    d.mkdir(parents=True)
    (d / "ROLE.md").write_text("---\nname: minimal\n---\nBody.\n")

    assert read_role_description(str(d)) == ""


# ---------------------------------------------------------------------------
# read_skill_description
# ---------------------------------------------------------------------------


def test_read_skill_description(tmp_path):
    """read_skill_description extracts description from SKILL.md frontmatter."""
    d = tmp_path / "skills" / "linter"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: linter\ndescription: Checks code quality\n---\nBody.\n"
    )

    assert read_skill_description(str(d)) == "Checks code quality"


def test_read_skill_description_missing(tmp_path):
    """read_skill_description returns empty string if no description."""
    d = tmp_path / "skills" / "empty"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: empty\n---\nBody.\n")

    assert read_skill_description(str(d)) == ""


def test_read_skill_description_no_file(tmp_path):
    """read_skill_description returns empty string if SKILL.md does not exist."""
    d = tmp_path / "skills" / "nofile"
    d.mkdir(parents=True)

    assert read_skill_description(str(d)) == ""


# ---------------------------------------------------------------------------
# Available Skills section
# ---------------------------------------------------------------------------


def test_available_skills_section_appended(tmp_path):
    """Available Skills section is appended when global_skills is provided."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    resolved = {
        "slug": "worker",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(
        resolved,
        global_skills=[
            ("linter", "Checks code quality"),
            ("formatter", "Formats code"),
        ],
    )

    assert "## Available Skills" in result
    assert "- **linter**: Checks code quality" in result
    assert "- **formatter**: Formats code" in result


def test_available_skills_before_delegation(tmp_path):
    """Available Skills section appears between role body and delegation."""
    role_path = _write_role(tmp_path, "lead", "You lead.")

    resolved = {
        "slug": "lead",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(
        resolved,
        global_skills=[("linter", "Checks code")],
        delegatable_roles=[("fixer", "Fixes bugs")],
    )

    role_pos = result.index("## Role: lead")
    skills_pos = result.index("## Available Skills")
    delegation_pos = result.index("## Delegation")
    assert role_pos < skills_pos < delegation_pos


def test_no_available_skills_when_none(tmp_path):
    """No Available Skills section when global_skills is None."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    resolved = {
        "slug": "worker",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(resolved, global_skills=None)
    assert "Available Skills" not in result


def test_no_available_skills_when_empty(tmp_path):
    """No Available Skills section when global_skills is empty."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    resolved = {
        "slug": "worker",
        "kind": "role",
        "version": "1.0.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }

    result = build_prompt(resolved, global_skills=[])
    assert "Available Skills" not in result


# ---------------------------------------------------------------------------
# validate_frontmatter_slug
# ---------------------------------------------------------------------------


def test_validate_frontmatter_slug_matching(tmp_path):
    d = tmp_path / "skills" / "my-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: my-skill\ndescription: test\n---\nBody.\n")
    validate_frontmatter_slug(str(d), "my-skill", "skill")


def test_validate_frontmatter_slug_mismatch(tmp_path):
    d = tmp_path / "skills" / "my-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: wrong-name\ndescription: test\n---\nBody.\n")
    with pytest.raises(ValueError, match="does not match expected slug"):
        validate_frontmatter_slug(str(d), "my-skill", "skill")


def test_validate_frontmatter_slug_missing_name(tmp_path):
    d = tmp_path / "skills" / "my-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\ndescription: test\n---\nBody.\n")
    with pytest.raises(ValueError, match="missing the 'name' field"):
        validate_frontmatter_slug(str(d), "my-skill", "skill")


def test_validate_frontmatter_slug_no_file(tmp_path):
    d = tmp_path / "skills" / "my-skill"
    d.mkdir(parents=True)
    # No SKILL.md — should not raise
    validate_frontmatter_slug(str(d), "my-skill", "skill")


def test_validate_frontmatter_slug_role(tmp_path):
    d = tmp_path / "roles" / "my-role"
    d.mkdir(parents=True)
    (d / "ROLE.md").write_text("---\nname: my-role\ndescription: test\n---\nBody.\n")
    validate_frontmatter_slug(str(d), "my-role", "role")


def test_validate_frontmatter_slug_role_mismatch(tmp_path):
    d = tmp_path / "roles" / "my-role"
    d.mkdir(parents=True)
    (d / "ROLE.md").write_text("---\nname: other-role\ndescription: test\n---\nBody.\n")
    with pytest.raises(ValueError, match="does not match expected slug"):
        validate_frontmatter_slug(str(d), "my-role", "role")
