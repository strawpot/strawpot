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
    create_workspace,
    handle_delegate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill(base, slug, body="Skill body."):
    d = os.path.join(base, "skills", slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w") as f:
        f.write(f"---\nname: {slug}\ndescription: test\n---\n{body}\n")
    return d


def _write_role(base, slug, body="Role body.", description="test"):
    d = os.path.join(base, "roles", slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "ROLE.md"), "w") as f:
        f.write(
            f"---\nname: {slug}\ndescription: {description}\n---\n{body}\n"
        )
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
# Workspace staging
# ---------------------------------------------------------------------------


class TestCreateWorkspace:
    def test_workspace_directory_created(self, tmp_path):
        runtime_dir = str(tmp_path / "runtime")
        resolved = {"dependencies": []}

        workspace, skills, roles = create_workspace(
            runtime_dir, "agent_1", resolved
        )

        assert os.path.isdir(workspace)
        assert workspace == os.path.join(runtime_dir, "agents", "agent_1")

    def test_skills_staged(self, tmp_path):
        """Skill directories are symlinked into the workspace."""
        base = str(tmp_path / "registry")
        skill_path = _write_skill(base, "git-workflow", "Use git.")
        runtime_dir = str(tmp_path / "runtime")

        resolved = {
            "dependencies": [
                {
                    "slug": "git-workflow",
                    "kind": "skill",
                    "path": skill_path,
                    "version": "1.0",
                    "source": "local",
                },
            ],
        }

        workspace, skills_dirs, roles_dirs = create_workspace(
            runtime_dir, "agent_1", resolved
        )

        assert len(skills_dirs) == 1
        assert os.path.islink(skills_dirs[0]) or os.path.isdir(skills_dirs[0])
        staged = os.path.join(skills_dirs[0], "SKILL.md")
        assert os.path.isfile(staged)
        with open(staged) as f:
            assert "Use git." in f.read()

    def test_role_deps_symlinked(self, tmp_path):
        """Role dependencies are symlinked into workspace/roles/."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "reviewer")
        runtime_dir = str(tmp_path / "runtime")

        resolved = {
            "dependencies": [
                {
                    "slug": "reviewer",
                    "kind": "role",
                    "path": role_path,
                    "version": "1.0",
                    "source": "local",
                },
            ],
        }

        workspace, skills_dirs, roles_dirs = create_workspace(
            runtime_dir, "agent_1", resolved
        )

        assert len(skills_dirs) == 0
        assert len(roles_dirs) == 1
        assert os.path.islink(roles_dirs[0]) or os.path.isdir(roles_dirs[0])
        assert os.path.isfile(os.path.join(roles_dirs[0], "ROLE.md"))

    def test_mixed_dependencies(self, tmp_path):
        """Both skill and role dependencies are handled correctly."""
        base = str(tmp_path / "registry")
        skill_path = _write_skill(base, "testing", "Test things.")
        role_path = _write_role(base, "reviewer")
        runtime_dir = str(tmp_path / "runtime")

        resolved = {
            "dependencies": [
                {
                    "slug": "testing",
                    "kind": "skill",
                    "path": skill_path,
                    "version": "1.0",
                    "source": "local",
                },
                {
                    "slug": "reviewer",
                    "kind": "role",
                    "path": role_path,
                    "version": "1.0",
                    "source": "local",
                },
            ],
        }

        _, skills_dirs, roles_dirs = create_workspace(
            runtime_dir, "agent_1", resolved
        )

        assert len(skills_dirs) == 1
        assert len(roles_dirs) == 1


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
        runtime_dir = str(tmp_path / "runtime")

        handle_delegate(
            request=_make_request(),
            config=_make_config(),
            runtime=runtime,
            working_dir=str(tmp_path / "work"),
            runtime_dir=runtime_dir,
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
            runtime_dir=str(tmp_path / "runtime"),
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
            runtime_dir=str(tmp_path / "runtime"),
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
            runtime_dir=str(tmp_path / "runtime"),
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
            runtime_dir=str(tmp_path / "runtime"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: orch_dir if s == "orchestrator" else None,
        )

        kw = runtime.spawn.call_args.kwargs
        assert len(kw["roles_dirs"]) == 1
        assert kw["roles_dirs"][0].endswith(os.sep + "orchestrator")
        assert os.path.isfile(os.path.join(kw["roles_dirs"][0], "ROLE.md"))

    def test_requester_role_dir_not_duplicated(self, tmp_path):
        """If requester's role is already in dependencies, it's not added twice."""
        base = str(tmp_path / "registry")
        role_path = _write_role(base, "implementer", "Implement.")
        orch_dir = _write_role(base, "orchestrator", "Orchestrate.")

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
            runtime_dir=str(tmp_path / "runtime"),
            resolve_role=lambda slug, kind="role": resolved,
            resolve_role_dirs=lambda s: orch_dir if s == "orchestrator" else None,
        )

        kw = runtime.spawn.call_args.kwargs
        # Only one entry — the dependency symlink; requester not duplicated
        assert len(kw["roles_dirs"]) == 1

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
            runtime_dir=str(tmp_path / "runtime"),
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
            runtime_dir=str(tmp_path / "runtime"),
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
            runtime_dir=str(tmp_path / "runtime"),
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
            runtime_dir=str(tmp_path / "runtime"),
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
                runtime_dir=str(tmp_path / "runtime"),
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
                runtime_dir=str(tmp_path / "runtime"),
                resolve_role=lambda slug, kind="role": {},
                resolve_role_dirs=lambda s: None,
            )

        runtime.spawn.assert_not_called()


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_flow(self, tmp_path):
        """Full delegation flow: resolve → prompt → workspace → spawn → wait → result."""
        base = str(tmp_path / "registry")
        skill_path = _write_skill(base, "testing", "Write tests.")
        role_path = _write_role(
            base, "implementer", "You implement features."
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
        runtime_dir = str(tmp_path / "runtime")

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
            runtime_dir=runtime_dir,
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

        # Workspace created with symlinked skill
        assert os.path.isdir(kw["agent_workspace_dir"])
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
