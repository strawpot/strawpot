"""Build system prompt from resolved role + skills."""

from pathlib import Path

import yaml


def parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter delimited by ``---`` from markdown text.

    Returns:
        dict with ``frontmatter`` (parsed YAML dict) and ``body`` (remaining text).
    """
    if not text.startswith("---"):
        return {"frontmatter": {}, "body": text}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"frontmatter": {}, "body": text}
    fm = yaml.safe_load(parts[1]) or {}
    return {"frontmatter": fm, "body": parts[2]}


def validate_frontmatter_slug(
    package_path: str, expected_slug: str, kind: str
) -> None:
    """Validate that the frontmatter ``name`` matches the expected slug.

    Args:
        package_path: Directory containing the package's main markdown file.
        expected_slug: The slug derived from the directory name.
        kind: ``"skill"``, ``"role"``, ``"agent"``, or ``"memory"``.

    Raises:
        ValueError: If the ``name`` field is missing or does not match *expected_slug*.
    """
    filename = {"skill": "SKILL.md", "role": "ROLE.md", "agent": "AGENT.md", "memory": "MEMORY.md"}[kind]
    filepath = Path(package_path) / filename
    if not filepath.exists():
        return
    text = filepath.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    fm_name = parsed.get("frontmatter", {}).get("name")
    if fm_name is None:
        raise ValueError(
            f"{filename} in '{package_path}' is missing the 'name' field"
        )
    if fm_name != expected_slug:
        raise ValueError(
            f"{filename} name '{fm_name}' does not match expected slug "
            f"'{expected_slug}' in '{package_path}'"
        )


def build_prompt(
    role_slug: str,
    role_path: str,
    skills: list[tuple[str, str]] | None = None,
    delegatable_roles: list[tuple[str, str]] | None = None,
    requester_role: str | None = None,
    custom_prompt: str | None = None,
) -> str:
    """Build a system prompt from a role and its available skills.

    Args:
        role_slug: The role's slug identifier.
        role_path: Path to the role's package directory (contains ROLE.md).
        skills: optional list of (slug, description) tuples for all
            skills available to this agent (first-order dependencies,
            global skills, and built-ins combined).  Listed by description
            only — the agent reads ``skills/<slug>/SKILL.md`` for details.
            Callers are responsible for filtering to first-order deps and
            excluding duplicates between dependency and global skills.
        delegatable_roles: optional list of (slug, description) tuples.
            When provided, a Delegation section is appended listing
            roles the agent can delegate to via denden.
        requester_role: optional slug of the role that delegated this task.
            When provided, a Requester section is appended so the agent
            can communicate back via denden.
        custom_prompt: optional custom instructions from the user.

    Returns:
        System prompt string assembled in this order:

        1. Role body
        2. Custom instructions (if provided)
        3. Skills section (description listing)
        4. Delegation section
        5. Requester section

        Frontmatter is stripped; sections are separated by ``---``.
    """
    sections: list[str] = []

    root_body = _read_body(role_path, "role")
    sections.append(f"## Role: {role_slug}\n\n{root_body}")

    if custom_prompt:
        sections.append(f"## Custom Instructions\n\n{custom_prompt}")

    if skills:
        sections.append(_build_skills_section(skills))

    if delegatable_roles:
        sections.append(_build_delegation_section(delegatable_roles))

    if requester_role:
        sections.append(_build_requester_section(requester_role))

    return "\n---\n\n".join(sections)


def _build_skills_section(skills: list[tuple[str, str]]) -> str:
    """Build the Skills section listing dependency skills with descriptions."""
    lines = [
        "## Skills",
        "",
        "The following skills are available in `skills/<name>/`. "
        "Read the SKILL.md file for full details when needed.",
    ]
    for slug, description in skills:
        lines.append(f"- **{slug}**: {description}")
    return "\n".join(lines)



def _build_delegation_section(roles: list[tuple[str, str]]) -> str:
    """Build the delegation section listing delegatable roles."""
    lines = [
        "## Delegation",
        "",
        "You can delegate tasks to the following roles:",
    ]
    for slug, description in roles:
        lines.append(f"- **{slug}**: {description}")
    lines.append("")
    lines.append(
        "Use the exact slug shown above (e.g. `code-reviewer`) in `delegateTo` — "
        "spelling, hyphens, and case must match exactly. "
        "Using an unrecognized slug will fail with `DENY_ROLE_NOT_ALLOWED`."
    )
    lines.append("")
    lines.append(
        "Each role is described in `roles/<role-name>/ROLE.md`. Read the ROLE.md"
    )
    lines.append("file to learn more about the role before delegating.")
    lines.append("")
    lines.append(
        "To delegate, read `skills/denden/SKILL.md` and use the `delegate` "
        "command documented there. For tasks well-suited to a delegatable role, "
        "prefer delegating rather than handling them directly."
    )
    return "\n".join(lines)


def _build_requester_section(role_slug: str) -> str:
    """Build the requester section identifying who delegated this task."""
    return (
        "## Requester\n"
        "\n"
        f"This task was delegated to you by **{role_slug}**. "
        "If you need task clarification or domain knowledge, use the "
        "`denden` skill to ask your requester.\n"
        "\n"
        "Do NOT use `denden` to send your final results back. "
        "When your task is complete, write your output to stdout."
    )


def read_skill_description(skill_path: str) -> str:
    """Read the description from a SKILL.md frontmatter.

    Args:
        skill_path: Directory containing the SKILL.md file.

    Returns:
        The description string, or empty string if not found.
    """
    filepath = Path(skill_path) / "SKILL.md"
    if not filepath.exists():
        return ""
    text = filepath.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    return parsed.get("frontmatter", {}).get("description", "")


def read_role_description(role_path: str) -> str:
    """Read the description from a ROLE.md frontmatter.

    Useful for building the ``delegatable_roles`` list for
    :func:`build_prompt`.

    Args:
        role_path: Directory containing the ROLE.md file.

    Returns:
        The description string, or empty string if not found.
    """
    filepath = Path(role_path) / "ROLE.md"
    text = filepath.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    return parsed.get("frontmatter", {}).get("description", "")


def _read_body(package_path: str, kind: str) -> str:
    """Read the markdown body from a package's main file, stripping frontmatter."""
    filename = {"skill": "SKILL.md", "role": "ROLE.md", "agent": "AGENT.md", "memory": "MEMORY.md"}[kind]
    filepath = Path(package_path) / filename
    text = filepath.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    return parsed.get("body", "").strip()


