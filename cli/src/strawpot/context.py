"""Build system prompt from resolved role + skills."""

from pathlib import Path

from strawhub.frontmatter import parse_frontmatter


def build_prompt(
    resolved: dict,
    delegatable_roles: list[tuple[str, str]] | None = None,
) -> str:
    """Build a system prompt from a resolved role and its dependencies.

    Args:
        resolved: dict from strawhub.resolver.resolve(), with keys:
            slug, kind, version, path, source, dependencies.
            Dependencies are in topological order (leaves first).
        delegatable_roles: optional list of (slug, description) tuples.
            When provided, a Delegation section is appended listing
            roles the agent can delegate to via denden.

    Returns:
        System prompt string: skills first (resolver order), role last,
        frontmatter stripped, sections separated by ``---``.
        If delegatable_roles is provided, a Delegation section follows.
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
