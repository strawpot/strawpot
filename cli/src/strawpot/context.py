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


def build_prompt(
    resolved: dict,
    delegatable_roles: list[tuple[str, str]] | None = None,
    requester_role: str | None = None,
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

    Returns:
        System prompt string: skills first (resolver order), role last,
        frontmatter stripped, sections separated by ``---``.
        If delegatable_roles is provided, a Delegation section follows.
        If requester_role is provided, a Requester section follows.
    """
    sections: list[str] = []

    for dep in resolved.get("dependencies", []):
        body = _read_body(dep["path"], dep["kind"])
        sections.append(f"## {dep['kind'].capitalize()}: {dep['slug']}\n\n{body}")

    root_body = _read_body(resolved["path"], resolved["kind"])
    sections.append(
        f"## {resolved['kind'].capitalize()}: {resolved['slug']}\n\n{root_body}"
    )

    if delegatable_roles:
        sections.append(_build_delegation_section(delegatable_roles))

    if requester_role:
        sections.append(_build_requester_section(requester_role))

    return "\n---\n\n".join(sections)


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
        "Each role is described in `roles/<role-name>/ROLE.md`. Read the ROLE.md"
    )
    lines.append(
        "file to learn more about the role before delegating. Use the `denden`"
    )
    lines.append("skill to request delegation.")
    return "\n".join(lines)


def _build_requester_section(role_slug: str) -> str:
    """Build the requester section identifying who delegated this task."""
    return (
        "## Requester\n"
        "\n"
        f"This task was delegated to you by **{role_slug}**. "
        "Use the `denden` skill to communicate back to your requester."
    )


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
    """Read the markdown body from a SKILL.md or ROLE.md, stripping frontmatter."""
    filename = "SKILL.md" if kind == "skill" else "ROLE.md"
    filepath = Path(package_path) / filename
    text = filepath.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    return parsed.get("body", "").strip()
