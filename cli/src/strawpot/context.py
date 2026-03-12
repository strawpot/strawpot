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
    resolved: dict,
    delegatable_roles: list[tuple[str, str]] | None = None,
    requester_role: str | None = None,
    global_skills: list[tuple[str, str]] | None = None,
    custom_prompt: str | None = None,
) -> str:
    """Build a system prompt from a resolved role and its dependencies.

    Args:
        resolved: dict from strawhub.resolver.resolve(), with keys:
            slug, kind, version, path, source, dependencies.
            Dependencies are in topological order (leaves first).
        delegatable_roles: optional list of (slug, description) tuples.
            When provided, a Delegation section is appended listing
            roles the agent can delegate to via denden.
        requester_role: optional slug of the role that delegated this task.
            When provided, a Requester section is appended so the agent
            can communicate back via denden.
        global_skills: optional list of (slug, description) tuples for
            globally installed skills.  When provided, an Available Skills
            section is inserted after the role body.

    Returns:
        System prompt string: role first, then skills (resolver order),
        frontmatter stripped, sections separated by ``---``.
        If global_skills is provided, an Available Skills section follows.
        If delegatable_roles is provided, a Delegation section follows.
        If requester_role is provided, a Requester section follows.
    """
    sections: list[str] = []

    root_body = _read_body(resolved["path"], resolved["kind"])
    sections.append(
        f"## {resolved['kind'].capitalize()}: {resolved['slug']}\n\n{root_body}"
    )

    for dep in resolved.get("dependencies", []):
        body = _read_body(dep["path"], dep["kind"])
        sections.append(f"## {dep['kind'].capitalize()}: {dep['slug']}\n\n{body}")

    if global_skills:
        sections.append(_build_available_skills_section(global_skills))

    if delegatable_roles:
        sections.append(_build_delegation_section(delegatable_roles))

    if requester_role:
        sections.append(_build_requester_section(requester_role))

    if custom_prompt:
        sections.append(f"## Custom Instructions\n\n{custom_prompt}")

    return "\n---\n\n".join(sections)


def _build_available_skills_section(skills: list[tuple[str, str]]) -> str:
    """Build the Available Skills section listing global skills."""
    lines = [
        "## Available Skills",
        "",
        "The following skills are available in `skills/<name>/`. "
        "Read the SKILL.md file for full details.",
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
        "command documented there. This is the ONLY way to delegate work. "
        "Never attempt tasks yourself — always delegate via the denden skill."
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
