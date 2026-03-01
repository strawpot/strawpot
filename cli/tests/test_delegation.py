"""Tests for strawpot.delegation."""

import os
from unittest.mock import MagicMock

import pytest

from strawpot.agents.protocol import AgentHandle, AgentResult
from strawpot.config import StrawPotConfig
from strawpot.delegation import (
    DelegateRequest,
    DelegateResult,
    PolicyDenied,
    _build_delegatable_roles,
    _check_policy,
    _collect_transitive_skills,
    _parse_role_deps,
    _parse_skill_deps,
    create_agent_workspace,
    handle_delegate,
    stage_role,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill(base, slug, body="Skill body.", deps=None):
    """Write a SKILL.md file.

    Args:
        base: Base directory (skill will be at base/skills/<slug>/).
        slug: Skill slug.
        body: Markdown body.
        deps: Optional list of skill dependency slugs for frontmatter.
    """
    d = os.path.join(base, "skills", slug)
    os.makedirs(d, exist_ok=True)
    if deps:
        deps_yaml = "\n".join(f"      - {s}" for s in deps)
        fm = (
            f"---\n"
            f"name: {slug}\n"
            f"description: test\n"
            f"metadata:\n"
            f"  strawpot:\n"
            f"    dependencies:\n"
            f"{deps_yaml}\n"
            f"---\n"
        )
    else:
        fm = f"---\nname: {slug}\ndescription: test\n---\n"
    with open(os.path.join(d, "SKILL.md"), "w") as f:
        f.write(fm + body + "\n")
    return d


def _write_role(base, slug, body="Role body.", description="test",
                skill_deps=None, role_deps=None):
    """Write a ROLE.md file.

    Args:
        base: Base directory (role will be at base/roles/<slug>/).
        slug: Role slug.
        body: Markdown body.
        description: Role description.
        skill_deps: Optional list of skill dependency slugs.
        role_deps: Optional list of role dependency slugs.
    """
    d = os.path.join(base, "roles", slug)
    os.makedirs(d, exist_ok=True)
    if skill_deps or role_deps:
        deps_lines = []
        if skill_deps:
            deps_lines.append("      skills:")
            for s in skill_deps:
                deps_lines.append(f"        - {s}")
        if role_deps:
            deps_lines.append("      roles:")
            for r in role_deps:
                deps_lines.append(f"        - {r}")
        deps_yaml = "\n".join(deps_lines)
        fm = (
            f"---\n"
            f"name: {slug}\n"
            f"description: {description}\n"
            f"metadata:\n"
            f"  strawpot:\n"
            f"    dependencies:\n"
            f"{deps_yaml}\n"
            f"---\n"
        )
    else:
        fm = f"---\nname: {slug}\ndescription: {description}\n---\n"
    with open(os.path.join(d, "ROLE.md"), "w") as f:
        f.write(fm + body + "\n")
    return d


def _make_request(**overrides):
    defaults = {
        "role_slug": "implementer",
        "task_text": "Write tests",
        "parent_agent_id": "agent_parent",
        "parent_role": "orchestrator",
        "run_id": "run_abc",
        "depth": 0,
    }
    defaults.update(overrides)
    return DelegateRequest(**defaults)


def _make_config(**overrides):
    return StrawPotConfig(**overrides)


def _mock_runtime(summary="Done", output="ok", exit_code=0):
    runtime = MagicMock()
    runtime.name = "mock_runtime"
    runtime.spawn.return_value = AgentHandle(
        agent_id="agent_test", runtime_name="mock_runtime", pid=999
    )
    runtime.wait.return_value = AgentResult(
        summary=summary, output=output, exit_code=exit_code
    )
    return runtime


# ---------------------------------------------------------------------------
# Policy checks
# ---------------------------------------------------------------------------


class TestCheckPolicy:
    def test_allowed_roles_none_allows_all(self):
        """allowed_roles=None means all roles are allowed."""
        config = _make_config(allowed_roles=None)
        request = _make_request(role_slug="anything")
        _check_policy(request, config)  # should not raise

    def test_role_in_allowed_list(self):
        """Role in allowed_roles passes."""
        config = _make_config(allowed_roles=["implementer", "reviewer"])
        request = _make_request(role_slug="implementer")
        _check_policy(request, config)  # should not raise

    def test_role_not_in_allowed_list(self):
        """Role not in allowed_roles raises DENY_ROLE_NOT_ALLOWED."""
        config = _make_config(allowed_roles=["implementer"])
        request = _make_request(role_slug="admin")
        with pytest.raises(PolicyDenied, match="DENY_ROLE_NOT_ALLOWED"):
            _check_policy(request, config)

    def test_depth_under_limit(self):
        """depth + 1 <= max_depth passes."""
        config = _make_config(max_depth=3)
        request = _make_request(depth=1)
        _check_policy(request, config)  # should not raise

    def test_depth_at_limit(self):
        """depth + 1 > max_depth raises DENY_DEPTH_LIMIT."""
        config = _make_config(max_depth=3)
        request = _make_request(depth=3)
        with pytest.raises(PolicyDenied, match="DENY_DEPTH_LIMIT"):
            _check_policy(request, config)

    def test_depth_zero_first_delegation(self):
        """First delegation (depth=0) always passes depth check."""
        config = _make_config(max_depth=1)
        request = _make_request(depth=0)
        _check_policy(request, config)  # should not raise


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


class TestParseRoleDeps:
    def test_no_deps(self, tmp_path):
        """Role without deps returns empty lists."""
        role_path = _write_role(str(tmp_path), "basic")
        skill_slugs, role_slugs = _parse_role_deps(role_path)
        assert skill_slugs == []
        assert role_slugs == []

    def test_skill_deps(self, tmp_path):
        """Parses skill dependencies from frontmatter."""
        role_path = _write_role(
            str(tmp_path), "impl", skill_deps=["git-workflow", "testing"]
        )
        skill_slugs, role_slugs = _parse_role_deps(role_path)
        assert skill_slugs == ["git-workflow", "testing"]
        assert role_slugs == []

    def test_role_deps(self, tmp_path):
        """Parses role dependencies from frontmatter."""
        role_path = _write_role(
            str(tmp_path), "orchestrator",
            role_deps=["reviewer", "implementer"],
        )
        skill_slugs, role_slugs = _parse_role_deps(role_path)
        assert skill_slugs == []
        assert role_slugs == ["reviewer", "implementer"]

    def test_mixed_deps(self, tmp_path):
        """Parses both skill and role deps."""
        role_path = _write_role(
            str(tmp_path), "lead",
            skill_deps=["testing"],
            role_deps=["reviewer"],
        )
        skill_slugs, role_slugs = _parse_role_deps(role_path)
        assert skill_slugs == ["testing"]
        assert role_slugs == ["reviewer"]

    def test_version_specifiers_stripped(self, tmp_path):
        """Version specifiers are stripped from slugs."""
        role_path = _write_role(
            str(tmp_path), "impl", skill_deps=["git-workflow ^1.0"]
        )
        skill_slugs, _ = _parse_role_deps(role_path)
        assert skill_slugs == ["git-workflow"]

    def test_no_role_md(self, tmp_path):
        """Missing ROLE.md returns empty lists."""
        d = str(tmp_path / "roles" / "missing")
        os.makedirs(d, exist_ok=True)
        skill_slugs, role_slugs = _parse_role_deps(d)
        assert skill_slugs == []
        assert role_slugs == []


class TestParseSkillDeps:
    def test_no_deps(self, tmp_path):
        """Skill without deps returns empty list."""
        skill_path = _write_skill(str(tmp_path), "basic")
        assert _parse_skill_deps(skill_path) == []

    def test_with_deps(self, tmp_path):
        """Parses skill dependencies."""
        skill_path = _write_skill(
            str(tmp_path), "testing", deps=["git-workflow"]
        )
        assert _parse_skill_deps(skill_path) == ["git-workflow"]

    def test_no_skill_md(self, tmp_path):
        """Missing SKILL.md returns empty list."""
        d = str(tmp_path / "skills" / "missing")
        os.makedirs(d, exist_ok=True)
        assert _parse_skill_deps(d) == []


# ---------------------------------------------------------------------------
# Transitive skill collection
# ---------------------------------------------------------------------------


class TestCollectTransitiveSkills:
    def test_direct_only(self, tmp_path):
        """Collects directly listed skills."""
        base = str(tmp_path / "registry")
        skill_a = _write_skill(base, "skill-a")

        all_deps = [
            {"slug": "skill-a", "kind": "skill", "path": skill_a},
        ]

        result = _collect_transitive_skills(["skill-a"], all_deps)
        assert len(result) == 1
        assert result[0]["slug"] == "skill-a"

    def test_transitive(self, tmp_path):
        """Collects transitive skill deps via SKILL.md frontmatter."""
        base = str(tmp_path / "registry")
        skill_b = _write_skill(base, "skill-b")
        skill_a = _write_skill(base, "skill-a", deps=["skill-b"])

        all_deps = [
            {"slug": "skill-a", "kind": "skill", "path": skill_a},
            {"slug": "skill-b", "kind": "skill", "path": skill_b},
        ]

        result = _collect_transitive_skills(["skill-a"], all_deps)
        slugs = [d["slug"] for d in result]
        assert "skill-a" in slugs
        assert "skill-b" in slugs
        # Leaves first (topological order)
        assert slugs.index("skill-b") < slugs.index("skill-a")

    def test_excludes_skills_from_roles(self, tmp_path):
        """Does not include skills that are only reachable through roles."""
        base = str(tmp_path / "registry")
        skill_a = _write_skill(base, "skill-a")
        skill_from_role = _write_skill(base, "skill-from-role")

        all_deps = [
            {"slug": "skill-a", "kind": "skill", "path": skill_a},
            {"slug": "skill-from-role", "kind": "skill", "path": skill_from_role},
            {"slug": "sub-role", "kind": "role", "path": "/some/path"},
        ]

        # Only skill-a is a direct dep; skill-from-role belongs to sub-role
        result = _collect_transitive_skills(["skill-a"], all_deps)
        slugs = [d["slug"] for d in result]
        assert "skill-a" in slugs
        assert "skill-from-role" not in slugs

    def test_unknown_slug_ignored(self):
        """Unknown slugs are silently ignored."""
        result = _collect_transitive_skills(["nonexistent"], [])
        assert result == []


# ---------------------------------------------------------------------------
# Role staging
# ---------------------------------------------------------------------------


class TestStageRole:
    def test_creates_role_directory(self, tmp_path):
        """stage_role creates the role directory with ROLE.md."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "You implement things.")
        session_dir = str(tmp_path / "session")

        resolved = {
            "slug": "implementer",
            "path": role_path,
            "dependencies": [],
        }

        stage_role(session_dir, resolved)

        staged_dir = os.path.join(session_dir, "roles", "implementer")
        assert os.path.isdir(staged_dir)
        assert os.path.isfile(os.path.join(staged_dir, "ROLE.md"))

    def test_stages_transitive_skills(self, tmp_path):
        """Transitive skill deps are symlinked into skills/."""
        base = str(tmp_path / "registry")
        skill_b = _write_skill(base, "skill-b", "Base skill.")
        skill_a = _write_skill(base, "skill-a", "Top skill.", deps=["skill-b"])
        role_path = _write_role(base, "implementer", skill_deps=["skill-a"])
        session_dir = str(tmp_path / "session")

        resolved = {
            "slug": "implementer",
            "path": role_path,
            "dependencies": [
                {"slug": "skill-a", "kind": "skill", "path": skill_a,
                 "version": "1.0", "source": "local"},
                {"slug": "skill-b", "kind": "skill", "path": skill_b,
                 "version": "1.0", "source": "local"},
            ],
        }

        skills_dirs, roles_dirs = stage_role(session_dir, resolved)

        assert len(skills_dirs) == 2
        slugs = [os.path.basename(d) for d in skills_dirs]
        assert "skill-a" in slugs
        assert "skill-b" in slugs
        for d in skills_dirs:
            assert os.path.isfile(os.path.join(d, "SKILL.md"))

    def test_stages_direct_role_deps(self, tmp_path):
        """Direct role deps are symlinked into roles/."""
        base = str(tmp_path / "registry")
        reviewer_path = _write_role(base, "reviewer", "You review.")
        role_path = _write_role(base, "orchestrator", role_deps=["reviewer"])
        session_dir = str(tmp_path / "session")

        resolved = {
            "slug": "orchestrator",
            "path": role_path,
            "dependencies": [
                {"slug": "reviewer", "kind": "role", "path": reviewer_path,
                 "version": "1.0", "source": "local"},
            ],
        }

        skills_dirs, roles_dirs = stage_role(session_dir, resolved)

        assert len(roles_dirs) == 1
        assert os.path.basename(roles_dirs[0]) == "reviewer"
        assert os.path.isfile(os.path.join(roles_dirs[0], "ROLE.md"))

    def test_idempotent(self, tmp_path):
        """Second call returns same paths without re-creating."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer")
        session_dir = str(tmp_path / "session")

        resolved = {
            "slug": "implementer",
            "path": role_path,
            "dependencies": [],
        }

        r1 = stage_role(session_dir, resolved)
        r2 = stage_role(session_dir, resolved)
        assert r1 == r2

    def test_excludes_skills_from_dependent_roles(self, tmp_path):
        """Skills from dependent roles are NOT included."""
        base = str(tmp_path / "registry")
        sub_skill = _write_skill(base, "sub-skill", "Sub skill.")
        _write_role(base, "sub-role", skill_deps=["sub-skill"])
        own_skill = _write_skill(base, "own-skill", "Own skill.")
        role_path = _write_role(
            base, "main-role",
            skill_deps=["own-skill"],
            role_deps=["sub-role"],
        )
        session_dir = str(tmp_path / "session")

        resolved = {
            "slug": "main-role",
            "path": role_path,
            "dependencies": [
                {"slug": "own-skill", "kind": "skill", "path": own_skill,
                 "version": "1.0", "source": "local"},
                {"slug": "sub-skill", "kind": "skill", "path": sub_skill,
                 "version": "1.0", "source": "local"},
                {"slug": "sub-role", "kind": "role",
                 "path": os.path.join(base, "roles", "sub-role"),
                 "version": "1.0", "source": "local"},
            ],
        }

        skills_dirs, roles_dirs = stage_role(session_dir, resolved)

        skill_slugs = [os.path.basename(d) for d in skills_dirs]
        assert "own-skill" in skill_slugs
        assert "sub-skill" not in skill_slugs

        role_slugs = [os.path.basename(d) for d in roles_dirs]
        assert "sub-role" in role_slugs


class TestCreateAgentWorkspace:
    def test_creates_directory(self, tmp_path):
        session_dir = str(tmp_path / "session")
        workspace = create_agent_workspace(session_dir, "agent_1")
        assert os.path.isdir(workspace)
        assert workspace == os.path.join(session_dir, "agents", "agent_1")


# ---------------------------------------------------------------------------
# Delegatable roles
# ---------------------------------------------------------------------------


class TestBuildDelegatableRoles:
    def test_none_allowed_roles_returns_empty(self, tmp_path):
        """When allowed_roles is None, no delegatable roles are listed."""
        config = _make_config(allowed_roles=None)
        result = _build_delegatable_roles(config, "implementer", lambda s: None)
        assert result == []

    def test_excludes_current_role(self, tmp_path):
        """Current role is excluded from delegatable list."""
        base = str(tmp_path)
        _write_role(base, "implementer", description="Writes code")
        impl_dir = os.path.join(base, "roles", "implementer")

        config = _make_config(allowed_roles=["implementer", "reviewer"])
        result = _build_delegatable_roles(
            config,
            "implementer",
            lambda s: impl_dir if s == "implementer" else None,
        )
        assert all(slug != "implementer" for slug, _ in result)

    def test_includes_resolvable_roles(self, tmp_path):
        """Roles with resolvable directories are included."""
        base = str(tmp_path)
        rev_dir = _write_role(base, "reviewer", description="Reviews code")

        config = _make_config(allowed_roles=["implementer", "reviewer"])
        result = _build_delegatable_roles(
            config,
            "implementer",
            lambda s: rev_dir if s == "reviewer" else None,
        )
        assert result == [("reviewer", "Reviews code")]

    def test_excludes_requester_role(self, tmp_path):
        """Requester role is excluded from delegatable list."""
        base = str(tmp_path)
        impl_dir = _write_role(base, "implementer", description="Writes code")
        orch_dir = _write_role(base, "orchestrator", description="Orchestrates")

        config = _make_config(
            allowed_roles=["implementer", "orchestrator", "reviewer"]
        )

        def resolve(s):
            if s == "implementer":
                return impl_dir
            if s == "orchestrator":
                return orch_dir
            return None

        result = _build_delegatable_roles(
            config, "reviewer", resolve, requester_role="orchestrator"
        )
        slugs = [slug for slug, _ in result]
        assert "orchestrator" not in slugs
        assert "implementer" in slugs

    def test_skips_unresolvable_roles(self):
        """Roles that can't be resolved are skipped."""
        config = _make_config(allowed_roles=["implementer", "ghost"])
        result = _build_delegatable_roles(
            config, "orchestrator", lambda s: None
        )
        assert result == []


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestPromptBuilding:
    def test_prompt_passed_to_spawn(self, tmp_path):
        """role_prompt in spawn matches build_prompt output."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "You implement things.")

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [],
        }

        runtime = _mock_runtime()
        session_dir = str(tmp_path / "session")

        handle_delegate(
            request=_make_request(),
            config=_make_config(),
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            session_dir=session_dir,
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: None,
        )

        call_kwargs = runtime.spawn.call_args.kwargs
        assert "You implement things." in call_kwargs["role_prompt"]
        assert "## Role: implementer" in call_kwargs["role_prompt"]

    def test_delegatable_roles_in_prompt(self, tmp_path):
        """When sub-agent has delegatable roles, prompt includes delegation section."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "orchestrator", "You orchestrate.")
        rev_dir = _write_role(base, "reviewer", description="Reviews code")

        resolved = {
            "slug": "orchestrator",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [],
        }

        runtime = _mock_runtime()
        config = _make_config(allowed_roles=["orchestrator", "reviewer"])

        handle_delegate(
            request=_make_request(role_slug="orchestrator"),
            config=config,
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            session_dir=str(tmp_path / "session"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: rev_dir if s == "reviewer" else None,
        )

        call_kwargs = runtime.spawn.call_args.kwargs
        assert "## Delegation" in call_kwargs["role_prompt"]
        assert "**reviewer**" in call_kwargs["role_prompt"]

    def test_requester_role_in_prompt(self, tmp_path):
        """Prompt includes requester section with parent role."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "You implement.")

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [],
        }

        runtime = _mock_runtime()

        handle_delegate(
            request=_make_request(parent_role="team-lead"),
            config=_make_config(),
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            session_dir=str(tmp_path / "session"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: None,
        )

        call_kwargs = runtime.spawn.call_args.kwargs
        assert "## Requester" in call_kwargs["role_prompt"]
        assert "**team-lead**" in call_kwargs["role_prompt"]


# ---------------------------------------------------------------------------
# Spawn + wait
# ---------------------------------------------------------------------------


class TestSpawnAndWait:
    def test_spawn_called_with_correct_args(self, tmp_path):
        """runtime.spawn receives correct working_dir, task, and env vars."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "Implement.")

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [],
        }

        runtime = _mock_runtime()
        working = str(tmp_path / "work")
        request = _make_request(
            parent_agent_id="agent_p",
            run_id="run_42",
            task_text="Fix the bug",
        )

        handle_delegate(
            request=request,
            config=_make_config(denden_addr="127.0.0.1:9999"),
            runtime=runtime,
            working_dir=working,
            session_dir=str(tmp_path / "session"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: None,
        )

        kw = runtime.spawn.call_args.kwargs
        assert kw["working_dir"] == working
        assert kw["task"] == "Fix the bug"
        assert kw["memory_prompt"] == ""
        assert kw["env"]["DENDEN_ADDR"] == "127.0.0.1:9999"
        assert kw["env"]["DENDEN_PARENT_AGENT_ID"] == "agent_p"
        assert kw["env"]["DENDEN_RUN_ID"] == "run_42"
        assert kw["env"]["PERMISSION_MODE"] == "auto"
        assert "DENDEN_AGENT_ID" in kw["env"]

    def test_requester_role_dir_included(self, tmp_path):
        """roles_dirs includes the requester's role path when resolvable."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "Implement.")
        orch_dir = _write_role(base, "orchestrator", "Orchestrate.")

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [],
        }

        runtime = _mock_runtime()

        handle_delegate(
            request=_make_request(parent_role="orchestrator"),
            config=_make_config(),
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            session_dir=str(tmp_path / "session"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: orch_dir if s == "orchestrator" else None,
        )

        kw = runtime.spawn.call_args.kwargs
        assert len(kw["roles_dirs"]) == 1
        assert kw["roles_dirs"][0].endswith(os.sep + "orchestrator")
        assert os.path.isfile(os.path.join(kw["roles_dirs"][0], "ROLE.md"))

    def test_requester_role_dir_not_duplicated(self, tmp_path):
        """If requester's role is already in staged deps, it's not added twice."""
        base = str(tmp_path / "registry")
        orch_dir = _write_role(base, "orchestrator", "Orchestrate.")
        role_path = _write_role(
            base, "implementer", "Implement.",
            role_deps=["orchestrator"],
        )

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [
                {
                    "slug": "orchestrator",
                    "kind": "role",
                    "path": orch_dir,
                    "version": "1.0",
                    "source": "local",
                },
            ],
        }

        runtime = _mock_runtime()

        handle_delegate(
            request=_make_request(parent_role="orchestrator"),
            config=_make_config(),
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            session_dir=str(tmp_path / "session"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: orch_dir if s == "orchestrator" else None,
        )

        kw = runtime.spawn.call_args.kwargs
        # Only one entry for orchestrator — staged dep; requester not duplicated
        orch_entries = [
            d for d in kw["roles_dirs"]
            if os.path.basename(d) == "orchestrator"
        ]
        assert len(orch_entries) == 1

    def test_result_mapped_to_delegate_result(self, tmp_path):
        """AgentResult fields map to DelegateResult."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "Implement.")

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [],
        }

        runtime = _mock_runtime(
            summary="All done", output="detailed output", exit_code=1
        )

        result = handle_delegate(
            request=_make_request(),
            config=_make_config(),
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            session_dir=str(tmp_path / "session"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: None,
        )

        assert isinstance(result, DelegateResult)
        assert result.summary == "All done"
        assert result.output == "detailed output"
        assert result.exit_code == 1

    def test_wait_called_with_spawn_handle(self, tmp_path):
        """runtime.wait is called with the handle from spawn."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "Implement.")

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [],
        }

        runtime = _mock_runtime()

        handle_delegate(
            request=_make_request(),
            config=_make_config(),
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            session_dir=str(tmp_path / "session"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: None,
        )

        spawn_handle = runtime.spawn.return_value
        runtime.wait.assert_called_once_with(spawn_handle, timeout=None)

    def test_timeout_kills_agent(self, tmp_path):
        """When agent_timeout is set and agent is still alive, kill and return timeout result."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "Implement.")

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [],
        }

        runtime = _mock_runtime()
        runtime.is_alive.return_value = True  # simulate still alive after wait

        result = handle_delegate(
            request=_make_request(),
            config=_make_config(agent_timeout=60),
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            session_dir=str(tmp_path / "session"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: None,
        )

        spawn_handle = runtime.spawn.return_value
        runtime.wait.assert_called_once_with(spawn_handle, timeout=60)
        runtime.kill.assert_called_once_with(spawn_handle)
        assert result.exit_code == 1
        assert "timed out" in result.summary

    def test_no_timeout_skips_kill(self, tmp_path):
        """When agent_timeout is None, agent is not killed after wait."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "Implement.")

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [],
        }

        runtime = _mock_runtime()

        handle_delegate(
            request=_make_request(),
            config=_make_config(),
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            session_dir=str(tmp_path / "session"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: None,
        )

        runtime.kill.assert_not_called()


# ---------------------------------------------------------------------------
# Policy denial through handle_delegate
# ---------------------------------------------------------------------------


class TestHandleDelegatePolicyDenial:
    def test_denied_role_does_not_spawn(self, tmp_path):
        """PolicyDenied is raised before spawn when role is not allowed."""
        runtime = _mock_runtime()

        with pytest.raises(PolicyDenied, match="DENY_ROLE_NOT_ALLOWED"):
            handle_delegate(
                request=_make_request(role_slug="admin"),
                config=_make_config(allowed_roles=["implementer"]),
                runtime=runtime,
                working_dir=str(tmp_path),
                session_dir=str(tmp_path / "session"),
                resolve_role=lambda slug, kind="role": {},
                resolve_role_dirs=lambda s: None,
            )

        runtime.spawn.assert_not_called()

    def test_denied_depth_does_not_spawn(self, tmp_path):
        """PolicyDenied is raised before spawn when depth exceeds limit."""
        runtime = _mock_runtime()

        with pytest.raises(PolicyDenied, match="DENY_DEPTH_LIMIT"):
            handle_delegate(
                request=_make_request(depth=5),
                config=_make_config(max_depth=3),
                runtime=runtime,
                working_dir=str(tmp_path),
                session_dir=str(tmp_path / "session"),
                resolve_role=lambda slug, kind="role": {},
                resolve_role_dirs=lambda s: None,
            )

        runtime.spawn.assert_not_called()


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_flow(self, tmp_path):
        """Full delegation flow: resolve → prompt → stage → spawn → wait → result."""
        base = str(tmp_path / "registry")
        skill_path = _write_skill(base, "testing", "Write tests.")
        role_path = _write_role(
            base, "implementer", "You implement features.",
            skill_deps=["testing"],
        )

        resolved = {
            "slug": "implementer",
            "kind": "role",
            "version": "1.0",
            "path": role_path,
            "source": "local",
            "dependencies": [
                {
                    "slug": "testing",
                    "kind": "skill",
                    "path": skill_path,
                    "version": "1.0",
                    "source": "local",
                },
            ],
        }

        runtime = _mock_runtime(summary="Feature implemented", output="LGTM")
        working = str(tmp_path / "worktree")
        session_dir = str(tmp_path / "session")

        result = handle_delegate(
            request=_make_request(
                role_slug="implementer",
                task_text="Add login page",
                parent_agent_id="agent_orch",
                run_id="run_session",
                depth=0,
            ),
            config=_make_config(denden_addr="127.0.0.1:9700"),
            runtime=runtime,
            working_dir=working,
            session_dir=session_dir,
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: None,
        )

        # Result
        assert result.summary == "Feature implemented"
        assert result.output == "LGTM"

        # Spawn was called once
        runtime.spawn.assert_called_once()
        kw = runtime.spawn.call_args.kwargs

        # Prompt includes skill + role
        assert "## Skill: testing" in kw["role_prompt"]
        assert "## Role: implementer" in kw["role_prompt"]
        assert "Write tests." in kw["role_prompt"]
        assert "You implement features." in kw["role_prompt"]

        # Agent workspace created
        assert os.path.isdir(kw["agent_workspace_dir"])

        # Staged skill is accessible
        assert len(kw["skills_dirs"]) == 1
        assert os.path.isfile(
            os.path.join(kw["skills_dirs"][0], "SKILL.md")
        )
        assert os.path.islink(kw["skills_dirs"][0]) or os.path.isdir(
            kw["skills_dirs"][0]
        )

        # Task and env
        assert kw["task"] == "Add login page"
        assert kw["env"]["DENDEN_ADDR"] == "127.0.0.1:9700"
        assert kw["env"]["DENDEN_PARENT_AGENT_ID"] == "agent_orch"
        assert kw["env"]["DENDEN_RUN_ID"] == "run_session"
