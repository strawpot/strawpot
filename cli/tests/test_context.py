"""Tests for strawpot.context."""

import pytest

from strawpot.context import (
    build_prompt,
    read_role_description,
    read_skill_description,
    validate_frontmatter_slug,
)


def _write_skill(base, slug, body, description="test"):
    d = base / "skills" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {slug}\ndescription: {description}\n---\n{body}\n"
    )
    return str(d)


def _write_role(base, slug, body):
    d = base / "roles" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "ROLE.md").write_text(
        f"---\nname: {slug}\ndescription: test\n---\n{body}\n"
    )
    return str(d)


def test_role_no_skills(tmp_path):
    path = _write_role(tmp_path, "solo", "You are a solo agent.")

    result = build_prompt("solo", path)
    assert result == "## Role: solo\n\nYou are a solo agent."


def test_role_with_skills(tmp_path):
    """Skills are listed by description."""
    role_path = _write_role(tmp_path, "implementer", "You implement things.")

    result = build_prompt(
        "implementer",
        role_path,
        skills=[
            ("git-workflow", "Git branching workflow"),
            ("code-review", "Code review process"),
        ],
    )

    assert "## Role: implementer\n\nYou implement things." in result
    assert "## Skills" in result
    assert "- **git-workflow**: Git branching workflow" in result
    assert "- **code-review**: Code review process" in result


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

    result = build_prompt("complex", str(d))
    assert "---\nname:" not in result
    assert "metadata:" not in result
    assert "# Complex Role" in result
    assert "Body content here." in result


def test_no_skills_section_when_none(tmp_path):
    """No Skills section when skills is None."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    result = build_prompt("worker", role_path, skills=None)
    assert "Skills" not in result


def test_no_skills_section_when_empty(tmp_path):
    """No Skills section when skills is empty."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    result = build_prompt("worker", role_path, skills=[])
    assert "Skills" not in result


def test_custom_prompt_before_skills(tmp_path):
    """Custom instructions appear after role but before skill listings."""
    role_path = _write_role(tmp_path, "coder", "You code.")

    result = build_prompt(
        "coder",
        role_path,
        skills=[("git-workflow", "Git workflow")],
        custom_prompt="Always write tests first.",
    )

    role_pos = result.index("## Role: coder")
    custom_pos = result.index("## Custom Instructions")
    skill_pos = result.index("## Skills")
    assert role_pos < custom_pos < skill_pos
    assert "Always write tests first." in result


def test_skills_section_instructs_to_read(tmp_path):
    """Skills section tells the agent to read SKILL.md for full details."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    result = build_prompt(
        "worker",
        role_path,
        skills=[("linter", "Checks code quality")],
    )

    assert "Read the SKILL.md file for full details" in result
    assert "- **linter**: Checks code quality" in result


# ---------------------------------------------------------------------------
# Delegation section
# ---------------------------------------------------------------------------


def test_delegation_section_appended(tmp_path):
    """Delegation section is appended when delegatable_roles is provided."""
    role_path = _write_role(tmp_path, "orchestrator", "You orchestrate.")

    result = build_prompt(
        "orchestrator",
        role_path,
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
    assert "prefer delegating" in result


def test_delegation_with_skills(tmp_path):
    """Delegation section comes after skills section."""
    role_path = _write_role(tmp_path, "team-lead", "You lead the team.")

    result = build_prompt(
        "team-lead",
        role_path,
        skills=[("git-workflow", "Git workflow")],
        delegatable_roles=[("implementer", "Writes code")],
    )

    role_pos = result.index("## Role: team-lead")
    skill_pos = result.index("## Skills")
    delegation_pos = result.index("## Delegation")
    assert role_pos < skill_pos < delegation_pos


def test_no_delegation_when_none(tmp_path):
    """No delegation section when delegatable_roles is None."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    result = build_prompt("worker", role_path, delegatable_roles=None)
    assert "Delegation" not in result


def test_no_delegation_when_empty_list(tmp_path):
    """No delegation section when delegatable_roles is empty."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    result = build_prompt("worker", role_path, delegatable_roles=[])
    assert "Delegation" not in result


def test_delegation_single_role(tmp_path):
    """Delegation section works with a single role."""
    role_path = _write_role(tmp_path, "lead", "You lead.")

    result = build_prompt(
        "lead",
        role_path,
        delegatable_roles=[("fixer", "Fixes bugs and issues")],
    )

    assert "- **fixer**: Fixes bugs and issues" in result
    assert result.count("- **") == 1


def test_delegation_section_exact_format(tmp_path):
    """Delegation section matches the DESIGN.md format exactly."""
    role_path = _write_role(tmp_path, "orch", "Orchestrate.")

    result = build_prompt(
        "orch",
        role_path,
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
        "Use the exact slug shown above (e.g. `code-reviewer`) in `delegateTo` — "
        "spelling, hyphens, and case must match exactly. "
        "Using an unrecognized slug will fail with `DENY_ROLE_NOT_ALLOWED`.\n"
        "\n"
        "Each role is described in `roles/<role-name>/ROLE.md`. Read the ROLE.md\n"
        "file to learn more about the role before delegating.\n"
        "\n"
        "To delegate, read `skills/denden/SKILL.md` and use the `delegate` "
        "command documented there. For tasks well-suited to a delegatable role, "
        "prefer delegating rather than handling them directly."
    )

    assert result.endswith(expected_delegation)


# ---------------------------------------------------------------------------
# Requester section
# ---------------------------------------------------------------------------


def test_requester_section_appended(tmp_path):
    """Requester section is appended when requester_role is provided."""
    role_path = _write_role(tmp_path, "implementer", "You implement.")

    result = build_prompt("implementer", role_path, requester_role="team-lead")

    assert "\n---\n\n## Requester" in result
    assert "**team-lead**" in result
    assert "denden" in result


def test_requester_after_delegation(tmp_path):
    """Requester section comes after delegation section."""
    role_path = _write_role(tmp_path, "lead", "You lead.")

    result = build_prompt(
        "lead",
        role_path,
        delegatable_roles=[("fixer", "Fixes bugs")],
        requester_role="orchestrator",
    )

    delegation_pos = result.index("## Delegation")
    requester_pos = result.index("## Requester")
    assert delegation_pos < requester_pos


def test_no_requester_when_none(tmp_path):
    """No requester section when requester_role is None."""
    role_path = _write_role(tmp_path, "worker", "You work.")

    result = build_prompt("worker", role_path, requester_role=None)
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
