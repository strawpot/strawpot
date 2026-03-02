"""Memory registry — discover MEMORY.md manifests and resolve to MemorySpec."""

import importlib.util
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from strawpot.agents.registry import ValidationResult, _current_os
from strawpot.config import get_strawpot_home
from strawpot.memory.protocol import MemoryProvider


@dataclass
class MemorySpec:
    """Resolved memory manifest ready for loading."""

    name: str
    version: str
    script: str
    config: dict = field(default_factory=dict)
    env_schema: dict = field(default_factory=dict)
    tools: dict = field(default_factory=dict)


def parse_memory_md(path: Path) -> tuple[dict, str]:
    """Parse a MEMORY.md file into (frontmatter_dict, markdown_body).

    The file must start with ``---``, followed by YAML, then ``---``,
    then the markdown body.

    Raises:
        ValueError: If the file has no valid YAML frontmatter delimiters.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"MEMORY.md missing frontmatter: {path}")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"MEMORY.md missing closing frontmatter delimiter: {path}")
    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return frontmatter, body


def _resolve_script(memory_dir: Path, strawpot_meta: dict) -> str:
    """Resolve the provider script path from metadata.strawpot.memory_module.

    Args:
        memory_dir: Directory containing the MEMORY.md.
        strawpot_meta: The ``metadata.strawpot`` dict from frontmatter.

    Returns:
        Absolute path to the provider script.

    Raises:
        ValueError: If memory_module is missing or file does not exist.
    """
    script = strawpot_meta.get("memory_module")
    if not script:
        raise ValueError(
            "MEMORY.md must define metadata.strawpot.memory_module"
        )
    script_path = memory_dir / script
    if not script_path.is_file():
        raise ValueError(f"Memory provider script not found: {script_path}")
    return str(script_path.resolve())


def _merge_config(params: dict, user_config: dict) -> dict:
    """Merge MEMORY.md param defaults with user-provided config.

    Extracts ``default`` values from each param definition, then overlays
    user_config on top. User values take precedence.
    """
    defaults = {}
    for key, schema in params.items():
        if "default" in schema:
            defaults[key] = schema["default"]
    return {**defaults, **user_config}


def resolve_memory(
    name: str, project_dir: str, user_config: dict | None = None
) -> MemorySpec:
    """Resolve a memory provider name to a fully loaded MemorySpec.

    Resolution order:
        1. ``<project_dir>/.strawpot/memory/<name>/MEMORY.md`` (project-local)
        2. ``~/.strawpot/memory/<name>/MEMORY.md`` (global install)
        3. Built-in ``_builtin_memory/<name>/MEMORY.md`` (ships with strawpot)

    Args:
        name: Memory provider name (e.g. ``"strawpot-memory-local"``).
        project_dir: Project root directory.
        user_config: Per-provider config from ``[memory_config]`` in config.toml.

    Returns:
        Resolved MemorySpec.

    Raises:
        FileNotFoundError: If no MEMORY.md found in any search path.
    """
    candidates = [
        Path(project_dir) / ".strawpot" / "memory" / name,
        get_strawpot_home() / "memory" / name,
        Path(__file__).parent / "_builtin_memory" / name,
    ]

    memory_dir: Path | None = None
    for candidate in candidates:
        if (candidate / "MEMORY.md").is_file():
            memory_dir = candidate
            break

    if memory_dir is None:
        searched = [str(c / "MEMORY.md") for c in candidates]
        raise FileNotFoundError(
            f"Memory provider not found: {name!r}. Searched:\n"
            + "\n".join(f"  - {p}" for p in searched)
        )

    frontmatter, _body = parse_memory_md(memory_dir / "MEMORY.md")
    metadata = frontmatter.get("metadata", {})
    strawpot_meta = metadata.get("strawpot", {})

    script = _resolve_script(memory_dir, strawpot_meta)
    params = strawpot_meta.get("params", {})
    config = _merge_config(params, user_config or {})
    env_schema = strawpot_meta.get("env", {})
    tools = strawpot_meta.get("tools", {})
    version = metadata.get("version", "0.0.0")

    return MemorySpec(
        name=frontmatter.get("name", name),
        version=version,
        script=script,
        config=config,
        env_schema=env_schema,
        tools=tools,
    )


def load_provider(spec: MemorySpec) -> MemoryProvider:
    """Dynamically load a memory provider from a MemorySpec.

    Imports the script file, scans for a class that satisfies
    ``MemoryProvider``, and returns an instance.

    Args:
        spec: A resolved MemorySpec with an absolute script path.

    Returns:
        An instance of the first class found that satisfies MemoryProvider.

    Raises:
        ValueError: If no MemoryProvider implementation is found in the script.
    """
    mod_spec = importlib.util.spec_from_file_location(
        "_memory_provider", spec.script
    )
    mod = importlib.util.module_from_spec(mod_spec)  # type: ignore[arg-type]
    mod_spec.loader.exec_module(mod)  # type: ignore[union-attr]

    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if (
            isinstance(attr, type)
            and attr is not MemoryProvider
            and issubclass(attr, object)
        ):
            try:
                instance = attr()
            except TypeError:
                continue
            if isinstance(instance, MemoryProvider):
                return instance

    raise ValueError(
        f"No MemoryProvider implementation found in {spec.script}"
    )


def validate_memory(spec: MemorySpec) -> ValidationResult:
    """Validate that a memory provider's external dependencies are satisfied.

    Checks:
        - Each tool declared in ``spec.tools`` is found on PATH.
        - Each env var marked ``required: true`` in ``spec.env_schema``
          is set in the current environment.

    Args:
        spec: A resolved MemorySpec.

    Returns:
        ValidationResult with any missing tools or env vars.
    """
    result = ValidationResult()

    for tool_name, tool_meta in spec.tools.items():
        if shutil.which(tool_name) is None:
            install_hint = (tool_meta.get("install", {}) or {}).get(
                _current_os()
            )
            result.missing_tools.append((tool_name, install_hint))

    for var_name, var_meta in spec.env_schema.items():
        if var_meta.get("required") and var_name not in os.environ:
            result.missing_env.append(var_name)

    return result
