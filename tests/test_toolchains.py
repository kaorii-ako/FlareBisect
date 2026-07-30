import pytest

from flarebisect import toolchains


def write(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_text("{}")
    return tmp_path


def test_detects_node_from_package_json(tmp_path):
    repo = write(tmp_path, "package.json")
    assert toolchains.detect(repo).name == "node-npm"


def test_lockfile_beats_bare_manifest(tmp_path):
    repo = write(tmp_path, "package.json", "pnpm-lock.yaml")
    assert toolchains.detect(repo).name == "node-pnpm"


def test_detects_go(tmp_path):
    assert toolchains.detect(write(tmp_path, "go.mod")).name == "go"


def test_detects_rust(tmp_path):
    assert toolchains.detect(write(tmp_path, "Cargo.toml")).name == "rust"


def test_glob_marker_matches_csproj(tmp_path):
    assert toolchains.detect(write(tmp_path, "App.csproj")).name == "dotnet"


def test_no_toolchain_in_empty_dir(tmp_path):
    assert toolchains.detect(tmp_path) is None


def test_command_overrides_markers(tmp_path):
    # a Rust crate vendored inside a Node repo — the command is the better clue
    repo = write(tmp_path, "package.json")
    assert toolchains.detect(repo, "cargo test --release").name == "rust"


def test_command_head_skips_env_assignments():
    assert toolchains._command_head("CI=1 RUST_LOG=debug cargo test") == "cargo"


def test_command_head_strips_path_prefix():
    assert toolchains._command_head("./node_modules/.bin/jest --ci") == "jest"


def test_detect_all_finds_every_present_toolchain(tmp_path):
    repo = write(tmp_path, "package.json", "go.mod", "Makefile")
    names = {tc.name for tc in toolchains.detect_all(repo)}
    assert {"node-npm", "go", "make"} <= names


class TestResolvePlan:
    def test_fills_command_and_setup_from_toolchain(self, tmp_path):
        plan = toolchains.resolve_plan(write(tmp_path, "go.mod"), command=None, setup=None)
        assert plan.command == "go test ./..."
        assert plan.setup.startswith("go mod download")
        assert plan.command_source == "toolchain"
        assert plan.setup_source == "toolchain"

    def test_explicit_flags_win(self, tmp_path):
        plan = toolchains.resolve_plan(
            write(tmp_path, "go.mod"), command="go test -race ./pkg", setup="make deps"
        )
        assert plan.command == "go test -race ./pkg"
        assert plan.setup == "make deps"
        assert plan.command_source == "flag"
        assert plan.setup_source == "flag"

    def test_no_setup_disables_inferred_setup(self, tmp_path):
        plan = toolchains.resolve_plan(write(tmp_path, "Cargo.toml"), command=None, setup=None, no_setup=True)
        assert plan.setup is None
        assert plan.setup_source == "disabled"

    def test_python_infers_no_setup(self, tmp_path):
        plan = toolchains.resolve_plan(write(tmp_path, "pyproject.toml"), command=None, setup=None)
        assert plan.command == "pytest"
        assert plan.setup is None
        assert plan.setup_source == "none"

    def test_raises_when_nothing_to_run(self, tmp_path):
        with pytest.raises(ValueError, match="no toolchain detected"):
            toolchains.resolve_plan(tmp_path, command=None, setup=None)

    def test_explicit_command_works_without_any_toolchain(self, tmp_path):
        plan = toolchains.resolve_plan(tmp_path, command="./flaky.sh", setup=None)
        assert plan.command == "./flaky.sh"
        assert plan.toolchain is None


class TestBuildEnv:
    def test_points_cache_vars_at_shared_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("GOMODCACHE", raising=False)
        env = toolchains.build_env(toolchains.BY_NAME["go"])
        assert str(tmp_path) in env["GOMODCACHE"]

    def test_respects_a_cache_var_the_caller_already_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.setenv("GOMODCACHE", "/my/own/cache")
        env = toolchains.build_env(toolchains.BY_NAME["go"])
        assert env["GOMODCACHE"] == "/my/own/cache"

    def test_share_cache_off_leaves_env_alone(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        monkeypatch.delenv("GOMODCACHE", raising=False)
        env = toolchains.build_env(toolchains.BY_NAME["go"], share_cache=False)
        assert "GOMODCACHE" not in env

    def test_no_toolchain_returns_plain_environ(self):
        assert toolchains.build_env(None) is not None
