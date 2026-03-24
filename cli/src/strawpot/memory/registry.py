"""Memory registry — discover MEMORY.md manifests and resolve to MemorySpec."""

import importlib
import importlib.metadata
import importlib.util
import logging
import re
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from strawpot.agents.registry import ValidationResult, _current_os
from strawpot.config import get_strawpot_home
from strawpot_memory.memory_protocol import MemoryProvider


log = logging.getLogger(__name__)


@dataclass
class MemorySpec:
    """Resolved memory manifest ready for loading."""

    name: str
    version: str
    script: str = ""
    config: dict = field(default_factory=dict)
    env_schema: dict = field(default_factory=dict)
    tools: dict = field(default_factory=dict)
    pip: str = ""
    module_path: str = ""


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


def _resolve_script(memory_dir: Path, strawpot_meta: dict) -> tuple[str, str, str]:
    """Resolve the provider module from metadata.strawpot.

    When ``pip`` is present, ``memory_module`` is treated as a dotted Python
    import path (e.g. ``dial_memory.provider``).  Otherwise it is a file path
    relative to the MEMORY.md directory.

    Returns:
        ``(script_path, pip_package, module_path)`` — only one of
        ``script_path`` or ``module_path`` will be non-empty.

    Raises:
        ValueError: If memory_module is missing or (for file mode) file
            does not exist.
    """
    module = strawpot_meta.get("memory_module")
    if not module:
        raise ValueError(
            "MEMORY.md must define metadata.strawpot.memory_module"
        )

    pip_package = strawpot_meta.get("pip", "")
    if pip_package:
        # pip-based: memory_module is a dotted import path
        return ("", pip_package, module)

    # File-based: memory_module is a relative file path
    script_path = memory_dir / module
    if not script_path.is_file():
        raise ValueError(f"Memory provider script not found: {script_path}")
    return (str(script_path.resolve()), "", "")


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
        1. ``<project_dir>/.strawpot/memories/<name>/MEMORY.md`` (project-local)
        2. ``~/.strawpot/memories/<name>/MEMORY.md`` (global install)

    Args:
        name: Memory provider name (e.g. ``"strawpot-memory-local"``).
        project_dir: Project root directory.
        user_config: Per-provider config from ``[memory_config]`` in strawpot.toml.

    Returns:
        Resolved MemorySpec.

    Raises:
        FileNotFoundError: If no MEMORY.md found in any search path.
    """
    candidates = [
        Path(project_dir) / ".strawpot" / "memories" / name,
        get_strawpot_home() / "memories" / name,
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

    script, pip_package, module_path = _resolve_script(memory_dir, strawpot_meta)
    params = strawpot_meta.get("params", {})
    config = _merge_config(params, user_config or {})

    # Resolve relative storage_dir to absolute path based on project_dir
    # so the provider doesn't depend on CWD.
    if "storage_dir" in config:
        sd = Path(os.path.expandvars(os.path.expanduser(config["storage_dir"])))
        if not sd.is_absolute():
            config["storage_dir"] = str(Path(project_dir) / sd)

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
        pip=pip_package,
        module_path=module_path,
    )


def _pip_install(requirement: str) -> None:
    """Install or upgrade a Python package via pip.

    Raises:
        RuntimeError: If called outside a virtual environment.
    """
    if sys.prefix == sys.base_prefix:
        raise RuntimeError(
            "Refusing to install packages outside a virtual environment. "
            "Please activate a venv first."
        )
    log.info("Installing %s via pip...", requirement)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", requirement],
        stdout=subprocess.DEVNULL,
    )


def _check_requirement(pip_requirement: str) -> bool:
    """Check if the installed package satisfies the pip requirement.

    Returns True if the requirement is satisfied, False if install/upgrade
    is needed.  Uses ``packaging`` if available for fast version comparison,
    falls back to calling pip otherwise.
    """
    # Extract package name (e.g. "dial-memory>=0.1.4" -> "dial-memory")
    match = re.match(r"^([A-Za-z0-9_.-]+)", pip_requirement)
    if not match:
        return False
    pkg_name = match.group(1)

    try:
        installed = importlib.metadata.version(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        return False

    # No version specifier — installed is enough
    if pkg_name == pip_requirement:
        return True

    try:
        from packaging.requirements import Requirement
        from packaging.version import Version

        return Version(installed) in Requirement(pip_requirement).specifier
    except Exception:
        # packaging unavailable — fall back to pip install (no-op if satisfied)
        _pip_install(pip_requirement)
        return True


def _load_module(spec: MemorySpec):
    """Import the provider module, auto-installing pip packages if needed."""
    if spec.module_path:
        # pip-based provider — check version requirement
        if spec.pip and not _check_requirement(spec.pip):
            _pip_install(spec.pip)

        try:
            return importlib.import_module(spec.module_path)
        except ImportError:
            if not spec.pip:
                raise
            _pip_install(spec.pip)
            return importlib.import_module(spec.module_path)

    # File-based provider
    script_path = Path(spec.script)
    parent_dir = script_path.parent

    # If the provider directory is a Python package (has __init__.py),
    # add its parent to sys.path and import as a package module so
    # relative imports work.
    if (parent_dir / "__init__.py").is_file():
        pkg_name = parent_dir.name
        module_name = f"{pkg_name}.{script_path.stem}"
        parent_of_pkg = str(parent_dir.parent)
        if parent_of_pkg not in sys.path:
            sys.path.insert(0, parent_of_pkg)
        return importlib.import_module(module_name)

    mod_spec = importlib.util.spec_from_file_location(
        "_memory_provider", spec.script
    )
    mod = importlib.util.module_from_spec(mod_spec)  # type: ignore[arg-type]
    mod_spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def load_provider(spec: MemorySpec) -> MemoryProvider:
    """Dynamically load a memory provider from a MemorySpec.

    For pip-based providers (``spec.module_path`` is set), imports via
    ``importlib.import_module`` and auto-installs the pip package on
    ``ImportError``.  For file-based providers, loads from ``spec.script``.

    Scans the loaded module for a class satisfying ``MemoryProvider``
    and returns an instance.

    Args:
        spec: A resolved MemorySpec.

    Returns:
        An instance of the first class found that satisfies MemoryProvider.

    Raises:
        ValueError: If no MemoryProvider implementation is found.
    """
    mod = _load_module(spec)
    source = spec.module_path or spec.script

    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if (
            isinstance(attr, type)
            and attr is not MemoryProvider
            and issubclass(attr, object)
        ):
            try:
                instance = attr(config=spec.config)
            except TypeError:
                try:
                    instance = attr()
                except TypeError:
                    continue
            if isinstance(instance, MemoryProvider):
                return instance

    raise ValueError(
        f"No MemoryProvider implementation found in {source}"
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
