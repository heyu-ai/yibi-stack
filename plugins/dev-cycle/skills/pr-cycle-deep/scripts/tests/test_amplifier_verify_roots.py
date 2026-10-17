"""以真實 Git checkout 與 trace checker 守住消費端的 spec 根目錄契約。"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "amplifier-verify.py"
_CHECKER = Path(__file__).resolve().parents[6] / "plugins/sdd/scripts/check_testplan_trace.py"
_spec = importlib.util.spec_from_file_location("amplifier_verify_roots", _SCRIPT)
av = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = av
_spec.loader.exec_module(av)

_PLAN = """trace: enforced

| TC-ID | Kind | Test Purpose |
|-------|------|--------------|
| ROOT-001 | auto | root detection |
"""


def _git(repo: Path, *args: str) -> str:
    """只操作測試建立的儲存庫，不讀使用者 Git 設定。"""
    result = subprocess.run(  # nosec B603 B607
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _write(repo: Path, path: str, text: str) -> Path:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


@pytest.fixture
def consumer_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "consumer"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _write(repo, "README.txt", "consumer\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo


def _change(repo: Path, root: str, name: str = "demo", *, bound: bool = False) -> str:
    path = f"{root}/changes/{name}/testplan.md"
    _write(repo, path, _PLAN)
    _write(repo, f"{root}/changes/{name}/proposal.md", "---\ntype: feat\n---\n")
    _write(repo, f"{root}/changes/{name}/tasks.md", "- [x] root contract verified\n")
    if bound:
        _write(repo, "tests/test_root.py", 'def test_root():\n    """tc: ROOT-001"""\n    pass\n')
    return path


def _modified(path: str) -> dict[str, str]:
    return {"status": "modified", "filename": path}


def _run_verifier(
    repo: Path,
    tmp_path: Path,
    files: list[dict[str, str]],
    *,
    cwd: Path | None = None,
    change: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """只替換外部 GitHub API；Git 根目錄、設定解析與追溯檢查皆執行真實程式。"""
    home = tmp_path / "home"
    registry = home / ".claude/plugins/installed_plugins.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps({"plugins": {"sdd@yibi-stack": [{"installPath": str(_CHECKER.parent.parent)}]}}),
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    metadata = {
        "baseRefOid": "base-oid",
        "headRefOid": _git(repo, "rev-parse", "HEAD"),
        "changedFiles": len(files),
    }
    diff = "".join(
        f"diff --git a/{record.get('previous_filename', record['filename'])} "
        f"b/{record['filename']}\n"
        for record in files
    )
    gh = bin_dir / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"metadata = {metadata!r}\nfiles = {files!r}\ndiff = {diff!r}\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['repo', 'view']:\n    print('owner/consumer')\n"
        "elif args[:2] == ['pr', 'view']:\n    print(json.dumps(metadata))\n"
        "elif args[:1] == ['api']:\n    print(json.dumps([files]))\n"
        "elif args[:2] == ['pr', 'diff']:\n    print(diff, end='')\n"
        "else:\n    sys.exit(97)\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    args = [sys.executable, str(_SCRIPT), "--pr", "42"]
    if change is not None:
        args.extend(["--change", change])
    return subprocess.run(  # nosec B603
        args,
        cwd=cwd or repo,
        env={**os.environ, "HOME": str(home), "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    ("root", "config"),
    [
        ("openspec", None),
        ("docs/openspec", None),
        ("openspec", "{}\n"),
        ("docs/openspec", "workflow: spectra\n"),
        ("openspec", "spec_dir: openspec\n"),
        ("docs/openspec", "spec_dir: docs/openspec\n"),
        ("docs/specs", "spec_dir: docs/specs\n"),
        ("docs/specs", 'spec_dir: "docs/specs" # current layout\n'),
        ("docs/specs", "spec_dir: 'docs/specs'\n"),
        ("docs/specs", '{spec_dir: "docs/specs", workflow: spectra}\n'),
        ("specs.v2", 'spec_dir: "specs.v2"\n'),
        ("docs/specs", 'spec_dir: "./docs//specs/"\n'),
        (" docs/specs ", 'spec_dir: " docs/specs "\n'),
        ("-specs", 'spec_dir: "-specs"\n'),
    ],
)
def test_cli_gates_enforced_plan_in_selected_spec_root(consumer_repo, tmp_path, root, config):
    """根目錄偵測成功仍必須真正擋下未綁定的 TC，不是只印出偵測訊息。"""
    if config is not None:
        _write(consumer_repo, ".spectra.yaml", config)
    path = _change(consumer_repo, root)
    result = _run_verifier(consumer_repo, tmp_path, [_modified(path)])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[MUST]" in result.stdout and "missing:" in result.stdout
    assert "ROOT-001" in result.stdout
    assert "找不到 active change" not in result.stderr


@pytest.mark.parametrize("root", ["docs/specs", "openspec", "docs/openspec"])
def test_cli_configured_missing_plan_is_not_masked_by_a_legacy_namesake(
    consumer_repo, tmp_path, root
):
    """明確設定的目前 change 缺少必要 plan 時，不可借舊版同名 plan 放行。"""
    _write(consumer_repo, ".spectra.yaml", f"spec_dir: {root}\n")
    _write(consumer_repo, f"{root}/changes/demo/proposal.md", "---\ntype: feat\n---\n")
    legacy = "openspec" if root != "openspec" else "docs/openspec"
    _change(consumer_repo, legacy, bound=True)
    result = _run_verifier(consumer_repo, tmp_path, [_modified(f"{root}/changes/demo/proposal.md")])
    assert result.returncode == 2, result.stdout + result.stderr
    assert f"Expected at {root}/changes/demo/testplan.md" in result.stderr


def test_cli_traces_bound_custom_plan_instead_of_legacy_namesake(consumer_repo, tmp_path):
    """相同 slug 的舊根目錄不可取代設定根目錄，checker 也必須查到同一份 plan。"""
    _write(consumer_repo, ".spectra.yaml", "spec_dir: docs/specs\n")
    path = _change(consumer_repo, "docs/specs", bound=True)
    legacy = _change(consumer_repo, "openspec")
    _write(consumer_repo, legacy, _PLAN.replace("ROOT-001", "LEGACY-001"))
    result = _run_verifier(consumer_repo, tmp_path, [_modified(path)])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "spectra change detected: demo" in result.stdout
    assert "[MUST]" not in result.stdout


@pytest.mark.parametrize(
    ("source", "destination", "active"),
    [
        ("openspec/changes/demo", "docs/specs/changes/demo", True),
        ("docs/openspec/changes/demo", "docs/specs/changes/demo", True),
        ("docs/specs/changes/demo", "docs/openspec/changes/demo", True),
        ("docs/specs/changes/demo", "openspec/changes/demo", True),
        ("openspec/changes/archive/2026-10-17-demo", "docs/specs/changes/demo", True),
        ("docs/specs/changes/archive/2026-10-17-demo", "docs/openspec/changes/demo", True),
        ("openspec/changes/demo", "docs/specs/changes/archive/2026-10-17-demo", False),
        ("docs/specs/changes/demo", "docs/openspec/changes/archive/2026-10-17-demo", False),
    ],
)
def test_cli_cross_root_rename_uses_current_active_or_archived_destination(
    consumer_repo, tmp_path, source, destination, active
):
    """舊路徑已不存在時仍檢查實際目的目錄；封存方向則保持無需 gate。"""
    _write(consumer_repo, ".spectra.yaml", "spec_dir: docs/specs\n")
    (consumer_repo / "docs/specs").mkdir(parents=True, exist_ok=True)
    path = f"{destination}/testplan.md"
    _write(consumer_repo, path, _PLAN)
    _write(consumer_repo, f"{destination}/tasks.md", "- [x] root contract verified\n")
    files = [{"status": "renamed", "previous_filename": f"{source}/testplan.md", "filename": path}]
    result = _run_verifier(consumer_repo, tmp_path, files)
    assert result.returncode == (1 if active else 0), result.stdout + result.stderr
    if active:
        assert "[MUST]" in result.stdout and "ROOT-001" in result.stdout
    else:
        assert "exists only in the archive" in result.stdout


def test_cli_custom_archive_only_deletion_skips_without_a_directory(consumer_repo, tmp_path):
    _write(consumer_repo, ".spectra.yaml", "spec_dir: docs/specs\n")
    (consumer_repo / "docs/specs").mkdir(parents=True)
    files = [
        {"status": "removed", "filename": "docs/specs/changes/archive/2026-10-17-old/tasks.md"}
    ]
    result = _run_verifier(consumer_repo, tmp_path, files)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "touches only archived material" in result.stdout


@pytest.mark.parametrize("active_root", ["docs/specs", "docs/openspec"])
def test_cli_custom_archive_does_not_mask_active_change(consumer_repo, tmp_path, active_root):
    _write(consumer_repo, ".spectra.yaml", "spec_dir: docs/specs\n")
    (consumer_repo / "docs/specs").mkdir(parents=True, exist_ok=True)
    active = _change(consumer_repo, active_root)
    result = _run_verifier(
        consumer_repo,
        tmp_path,
        [
            _modified("docs/specs/changes/archive/2026-10-17-old/tasks.md"),
            _modified(active),
        ],
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[MUST]" in result.stdout and "ROOT-001" in result.stdout


@pytest.mark.parametrize(
    "config",
    [
        "",
        "null\n",
        "[]\n",
        "spec_dir: [\n",
        "spec_dir:\n",
        "spec_dir: 42\n",
        "spec_dir: true\n",
        "spec_dir: []\n",
        "spec_dir: {}\n",
        'spec_dir: ""\n',
        "spec_dir: ../outside\n",
        "spec_dir: /tmp/outside\n",
        'spec_dir: "bad\\0path"\n',
    ],
)
def test_cli_invalid_configuration_is_fatal_even_without_spectra_paths(
    consumer_repo, tmp_path, config
):
    _write(consumer_repo, ".spectra.yaml", config)
    result = _run_verifier(consumer_repo, tmp_path, [])
    assert result.returncode == 2, result.stdout + result.stderr
    assert "[FAIL] Spectra 設定錯誤" in result.stderr
    assert "no spectra change" not in result.stdout


def test_cli_blank_root_is_invalid_even_when_a_whitespace_directory_exists(consumer_repo, tmp_path):
    """空白設定值仍屬設定錯誤，不因同名目錄存在而繞過字串驗證。"""
    (consumer_repo / "   ").mkdir()
    _write(consumer_repo, ".spectra.yaml", 'spec_dir: "   "\n')
    result = _run_verifier(consumer_repo, tmp_path, [])
    assert result.returncode == 2, result.stdout + result.stderr
    assert "no spectra change" not in result.stdout


@pytest.mark.parametrize("kind", ["directory", "invalid-encoding", "dangling-symlink"])
def test_cli_unreadable_configuration_is_fatal(consumer_repo, tmp_path, kind):
    config = consumer_repo / ".spectra.yaml"
    if kind == "directory":
        config.mkdir()
    elif kind == "invalid-encoding":
        config.write_bytes(b"\xff\xfe")
    else:
        config.symlink_to(consumer_repo / "missing.yaml")
    result = _run_verifier(consumer_repo, tmp_path, [])
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Spectra 設定錯誤" in result.stderr


def test_cli_missing_change_diagnostic_lists_configured_and_legacy_roots(consumer_repo, tmp_path):
    _write(consumer_repo, ".spectra.yaml", "spec_dir: docs/specs\n")
    (consumer_repo / "docs/specs").mkdir(parents=True)
    result = _run_verifier(
        consumer_repo, tmp_path, [_modified("docs/specs/changes/missing/tasks.md")]
    )
    assert result.returncode == 2
    for root in ("docs/specs", "openspec", "docs/openspec"):
        assert f"{root}/changes/missing/" in result.stderr
        assert f"{root}/changes/archive/<YYYY-MM-DD>-missing/" in result.stderr


def test_cli_explicit_change_uses_project_configuration(consumer_repo, tmp_path):
    _write(consumer_repo, ".spectra.yaml", "spec_dir: docs/specs\n")
    _change(consumer_repo, "docs/specs")
    result = _run_verifier(consumer_repo, tmp_path, [], change="demo")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ROOT-001" in result.stdout and "[MUST]" in result.stdout


def test_cli_reads_current_worktree_config_when_invoked_from_subdirectory(consumer_repo, tmp_path):
    _write(consumer_repo, ".spectra.yaml", "spec_dir: openspec\n")
    _git(consumer_repo, "add", ".")
    _git(consumer_repo, "commit", "-m", "main config")
    worktree = tmp_path / "review-worktree"
    _git(consumer_repo, "worktree", "add", "-b", "review", str(worktree))
    _write(worktree, ".spectra.yaml", "spec_dir: docs/specs\n")
    path = _change(worktree, "docs/specs")
    subdir = worktree / "nested/subdir"
    subdir.mkdir(parents=True)
    result = _run_verifier(worktree, tmp_path, [_modified(path)], cwd=subdir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[MUST]" in result.stdout and "ROOT-001" in result.stdout


def test_diff_helper_uses_the_same_custom_and_legacy_roots(tmp_path):
    _write(tmp_path, ".spectra.yaml", "spec_dir: docs/specs\n")
    (tmp_path / "docs/specs").mkdir(parents=True)
    roots = av.load_spec_roots(tmp_path)
    diff = (
        "diff --git a/openspec/changes/archive/2026-10-17-old/tasks.md "
        "b/docs/specs/changes/demo/tasks.md\n"
        "diff --git a/docs/specs/changes/demo/tasks.md b/docs/openspec/changes/demo/tasks.md\n"
        "+example b/docs/specs/changes/not-a-change/tasks.md\n"
    )
    refs = av.detect_change_refs_from_diff(diff, roots)
    assert refs.active_tree == ["demo"]
    assert refs.archive_tree == ["2026-10-17-old"]
    assert av.detect_change_from_diff(diff, roots) == "demo"


def test_cli_rejects_spec_root_symlink_outside_project(consumer_repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (consumer_repo / "specs").symlink_to(outside, target_is_directory=True)
    _write(consumer_repo, ".spectra.yaml", "spec_dir: specs\n")
    result = _run_verifier(consumer_repo, tmp_path, [])
    assert result.returncode == 2
    assert "Spectra 設定錯誤" in result.stderr


def test_cli_rejects_active_change_symlink_outside_project(consumer_repo, tmp_path):
    _write(consumer_repo, ".spectra.yaml", "spec_dir: docs/specs\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    change = consumer_repo / "docs/specs/changes/demo"
    change.parent.mkdir(parents=True)
    change.symlink_to(outside, target_is_directory=True)
    result = _run_verifier(consumer_repo, tmp_path, [_modified("docs/specs/changes/demo/tasks.md")])
    assert result.returncode == 2
    assert "change 目錄不可指向專案外" in result.stderr


@pytest.mark.parametrize("with_spec_path", [False, True], ids=["no-spec-paths", "default-change"])
@pytest.mark.parametrize(
    "kind", ["missing", "file", "dangling-symlink", "unreadable", "unsearchable"]
)
def test_cli_explicit_unavailable_root_is_fatal(consumer_repo, tmp_path, kind, with_spec_path):
    """明確根目錄的拼錯、檔案或不可讀狀態，不能以零命中或舊根目錄掩蓋。"""
    _write(consumer_repo, ".spectra.yaml", "spec_dir: docs/specs\n")
    root = consumer_repo / "docs/specs"
    root.parent.mkdir()
    if kind == "file":
        root.write_text("not a directory\n", encoding="utf-8")
    elif kind == "dangling-symlink":
        root.symlink_to(consumer_repo / "missing-root", target_is_directory=True)
    elif kind in {"unreadable", "unsearchable"}:
        root.mkdir()
        root.chmod(0o300 if kind == "unreadable" else 0o600)
        if os.access(root, os.R_OK | os.X_OK):
            root.chmod(0o700)
            pytest.skip("目前使用者可略過目錄權限，無法建立不可讀／搜尋的實際目錄")
    path = _change(consumer_repo, "openspec", bound=True) if with_spec_path else None
    try:
        result = _run_verifier(
            consumer_repo, tmp_path, [_modified(path)] if path is not None else []
        )
    finally:
        if kind in {"unreadable", "unsearchable"}:
            root.chmod(0o700)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "[FAIL] Spectra 設定錯誤" in result.stderr
    assert "規格根目錄" in result.stderr
    assert "no spectra change" not in result.stdout
    assert "spectra change detected" not in result.stdout


@pytest.mark.parametrize("config", [None, "{}\n", "workflow: spectra\n"])
def test_cli_absent_default_roots_allow_non_spec_pr(consumer_repo, tmp_path, config):
    """沒有明確根目錄時，尚未建立兩個標準佈局不代表設定錯誤。"""
    if config is not None:
        _write(consumer_repo, ".spectra.yaml", config)
    result = _run_verifier(consumer_repo, tmp_path, [_modified("README.txt")])
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "no spectra change"


@pytest.mark.parametrize("quote_path", ["true", "false"])
@pytest.mark.parametrize(
    "root",
    [
        "docs/my specs",
        "docs/規格",
        "docs/spec\troot",
        'docs/"specs"',
        "docs/spec\\root",
        " docs/specs ",
        "docs/path b/segment",
    ],
)
def test_real_git_diff_matches_rest_for_ordinary_paths(consumer_repo, root, quote_path):
    """真實 Git 的空白、C 引號、UTF-8 與跳脫路徑，與 REST 回傳相同實際 slug。"""
    _write(consumer_repo, ".spectra.yaml", json.dumps({"spec_dir": root}))
    path = f"{root}/changes/demo/tasks.md"
    _write(consumer_repo, path, f"-- a/{root}/changes/removed-decoy/tasks.md\nold\n")
    _git(consumer_repo, "add", ".")
    _git(consumer_repo, "commit", "-m", "original spec")
    _write(consumer_repo, path, f"++ b/{root}/changes/added-decoy/tasks.md\nnew\n")
    diff = _git(
        consumer_repo,
        "-c",
        f"core.quotePath={quote_path}",
        "diff",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
    )
    roots = av.load_spec_roots(consumer_repo)
    helper = av.detect_change_refs_from_diff(diff, roots)
    rest = av.derive_change_refs([av.PRFileChange("modified", path, path)], roots)
    assert helper.active_tree == ["demo"]
    assert rest.active_tree == ["demo"]
    assert helper.archive_tree == []
    assert rest.archive_tree == []
    assert av.detect_change_from_diff(diff, roots) == "demo"


@pytest.mark.parametrize(
    ("old_root", "new_root", "old_name", "new_name", "active", "archived"),
    [
        ("openspec", "docs/my specs", "old", "demo", ["old", "demo"], []),
        ("docs/規格", "docs/openspec", "old", "demo", ["old", "demo"], []),
        (
            'docs/"specs"',
            "openspec",
            "demo",
            "archive/2026-10-17-demo",
            ["demo"],
            ["2026-10-17-demo"],
        ),
        (
            "openspec",
            "docs/spec\\root",
            "archive/2026-10-17-demo",
            "demo",
            ["demo"],
            ["2026-10-17-demo"],
        ),
        ("docs/path b/segment", "openspec", "old", "demo", ["old", "demo"], []),
    ],
)
def test_real_git_pure_rename_matches_rest_for_both_sides(
    consumer_repo, old_root, new_root, old_name, new_name, active, archived
):
    """無 hunk 的純 rename 保留舊／新兩側，不能靠內容標頭才能發現 change。"""
    configured = new_root if new_root not in {"openspec", "docs/openspec"} else old_root
    _write(consumer_repo, ".spectra.yaml", json.dumps({"spec_dir": configured}))
    old = f"{old_root}/changes/{old_name}/tasks.md"
    new = f"{new_root}/changes/{new_name}/tasks.md"
    _write(consumer_repo, old, "unchanged spec\n")
    _git(consumer_repo, "add", ".")
    _git(consumer_repo, "commit", "-m", "before rename")
    (consumer_repo / new).parent.mkdir(parents=True)
    _git(consumer_repo, "mv", "--", old, new)
    (consumer_repo / configured).mkdir(parents=True, exist_ok=True)
    diff = _git(
        consumer_repo,
        "-c",
        "core.quotePath=true",
        "diff",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--cached",
        "--find-renames=100%",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
    )
    assert "similarity index 100%" in diff and "@@" not in diff
    roots = av.load_spec_roots(consumer_repo)
    helper = av.detect_change_refs_from_diff(diff, roots)
    rest = av.derive_change_refs([av.PRFileChange("renamed", old, new)], roots)
    assert helper.active_tree == active
    assert rest.active_tree == active
    assert helper.archive_tree == archived
    assert rest.archive_tree == archived


@pytest.mark.parametrize("entry_kind", ["archive-root", "verbatim", "dated"])
@pytest.mark.parametrize("explicit", [False, True], ids=["active-origin", "explicit-change"])
@pytest.mark.parametrize("outside", [False, True], ids=["internal-control", "escape"])
def test_cli_archive_lookup_rejects_escape_and_accepts_internal_control(
    consumer_repo, tmp_path, entry_kind, explicit, outside
):
    """由 active 來源或 --change 真正進入封存查找，逐一守住三個 containment guard。"""
    _write(consumer_repo, ".spectra.yaml", "spec_dir: docs/specs\n")
    root = consumer_repo / "docs/specs"
    root.mkdir(parents=True)
    archive = root / "changes/archive"
    target = tmp_path / "outside" if outside else consumer_repo / "internal-archive"
    target.mkdir()
    if entry_kind == "archive-root":
        (target / "2026-10-17-demo").mkdir()
        archive.parent.mkdir()
        archive.symlink_to(target, target_is_directory=True)
    else:
        archive.mkdir(parents=True)
        entry = archive / ("demo" if entry_kind == "verbatim" else "2026-10-17-demo")
        entry.symlink_to(target, target_is_directory=True)
    files = (
        []
        if explicit
        else [
            {
                "status": "renamed",
                "previous_filename": "docs/specs/changes/demo/tasks.md",
                "filename": "docs/specs/changes/archive/2026-10-17-demo/tasks.md",
            }
        ]
    )
    result = _run_verifier(consumer_repo, tmp_path, files, change="demo" if explicit else None)
    assert result.returncode == (2 if outside else 0), result.stdout + result.stderr
    if outside:
        assert "[FAIL] 無法解析 Spectra change 目錄" in result.stderr
        assert "archive" in result.stderr and "不可指向專案外" in result.stderr
        assert "exists only in the archive" not in result.stdout
        assert "touches only archived material" not in result.stdout
    else:
        assert "exists only in the archive" in result.stdout


@pytest.mark.parametrize("source_change", ["old", "archive/2026-10-17-old"])
def test_real_git_copy_does_not_gate_its_unchanged_source(consumer_repo, source_change):
    """真實 copy 只引入目的 change，不把未修改的 active／archive 來源當成本次變更。"""
    _write(consumer_repo, ".spectra.yaml", 'spec_dir: "docs/my specs"\n')
    old = f"openspec/changes/{source_change}/tasks.md"
    new = "docs/my specs/changes/demo/tasks.md"
    _write(consumer_repo, old, "content unique to the copy source\n")
    _git(consumer_repo, "add", ".")
    _git(consumer_repo, "commit", "-m", "copy source")
    _write(consumer_repo, new, (consumer_repo / old).read_text(encoding="utf-8"))
    _git(consumer_repo, "add", ".")
    diff = _git(
        consumer_repo,
        "diff",
        "--cached",
        "--find-copies-harder",
        "--find-copies=100%",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
    )
    assert f"\ncopy from {old}\n" in diff, "fixture 必須真正進入 Git copy 路徑"
    roots = av.load_spec_roots(consumer_repo)
    helper = av.detect_change_refs_from_diff(diff, roots)
    rest = av.derive_change_refs([av.PRFileChange("copied", old, new)], roots)
    assert helper.active_tree == ["demo"]
    assert rest.active_tree == ["demo"]
    assert helper.archive_tree == []
    assert rest.archive_tree == []
