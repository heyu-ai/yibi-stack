"""以真實 TypeScript AST 驗證 Vitest 綁定，不執行測試來源。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "vitest_trace.cjs"


def _source(root: Path, relative: str, content: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _invoke(
    root: Path, files: list[Path], helper: Path = HELPER
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("NODE_PATH", None)
    environment.pop("NODE_OPTIONS", None)
    return subprocess.run(  # nosec B603 B607
        ["node", "--no-global-search-paths", str(helper)],
        input=json.dumps({"files": [str(file) for file in files], "repo_root": str(root)}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=environment,
    )


def _bindings(root: Path, files: list[Path]) -> list[dict[str, object]]:
    result = _invoke(root, files)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


def test_alias_each_nested_describe_and_all_markers(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "src/login.test.tsx",
        """import { describe as group, test as scenario } from 'vitest';
group('login', () => {
  // tc: WRONG-SUITE-001
  group('validation', () => {
    scenario.each([[1], [2]])('rejects %s', (value: number) => {
      // tc: LOGIN-VL-001, LOGIN-VL-002
      // spec: login#require-password
      /**
       * tc: LOGIN-VL-003a
       * spec: login#reject-empty
       */
      const view = <button>{value}</button>;
      expect(view).toBeTruthy();
      /* tc: LOGIN-VL-004 */
    });
  });
});
""",
    )
    assert _bindings(tmp_path, [source]) == [
        {
            "nodeid": "src/login.test.tsx::login::validation::rejects %s@5",
            "tc_ids": ["LOGIN-VL-001", "LOGIN-VL-002", "LOGIN-VL-003a", "LOGIN-VL-004"],
            "spec_slugs": ["require-password", "reject-empty"],
        }
    ]


def test_tagged_each_namespace_and_inline_function(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "tests/table.spec.ts",
        """import * as vt from 'vitest';
vt.describe.each([1])('table %s', () => {
  vt.test.each`value | expected
    ${1} | ${2}
  `('row $value', function ({ value }: { value: number }) {
    /* tc: TABLE-DT-001, TABLE-DT-002 */
    /* spec: table#row-value */
    expect(value).toBe(1);
  });
});
""",
    )
    assert _bindings(tmp_path, [source]) == [
        {
            "nodeid": "tests/table.spec.ts::table %s::row $value@3",
            "tc_ids": ["TABLE-DT-001", "TABLE-DT-002"],
            "spec_slugs": ["row-value"],
        }
    ]


@pytest.mark.parametrize("extension", ["js", "jsx", "ts", "tsx"])
@pytest.mark.parametrize("convention", ["test", "spec"])
def test_globals_and_supported_file_extensions(
    tmp_path: Path, extension: str, convention: str
) -> None:
    filename = f"sample.{convention}.{extension}"
    source = _source(
        tmp_path,
        filename,
        "it('global', () => { /* tc: GLOBAL-VL-001 */ });\n",
    )
    assert _bindings(tmp_path, [source]) == [
        {
            "nodeid": f"{filename}::global@1",
            "tc_ids": ["GLOBAL-VL-001"],
            "spec_slugs": [],
        }
    ]


def test_fixture_text_jsx_and_nested_callbacks_never_bind(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "tests/false-positive.test.tsx",
        """describe('suite', () => {
  // tc: FALSE-SUITE-001
  test('real', () => {
    const string = '// tc: FALSE-STRING-001';
    const template = `\n// tc: FALSE-TEMPLATE-001\n`;
    const regex = /tc: FALSE-REGEX-001/;
    const jsx = <div>
      // tc: FALSE-JSX-001
      {/* tc: FALSE-JSX-002 */}
    </div>;
    const fixture = {
      // tc: FALSE-FIXTURE-001
      label: 'tc: FALSE-FIXTURE-002',
    };
    function helper() {
      // tc: FALSE-HELPER-001
    }
    const closure = () => {
      // tc: FALSE-CLOSURE-001
    };
    [1].forEach(() => {
      // tc: FALSE-CALLBACK-001
    });
    class Fixture {
      method() { /* tc: FALSE-METHOD-001 */ }
    }
    // prose mentioning tc: FALSE-PROSE-001
    // tc: REAL-VL-001
    // spec: real#explicit-comment
  });
});
function unused() {
  test('never registered', () => { /* tc: FALSE-UNUSED-001 */ });
}
const unusedArrow = () => test('never registered', () => {
  // tc: FALSE-UNUSED-002
});
beforeEach(() => {
  test('invalid nested registration', () => { /* tc: FALSE-HOOK-001 */ });
});
""",
    )
    assert _bindings(tmp_path, [source]) == [
        {
            "nodeid": "tests/false-positive.test.tsx::suite::real@3",
            "tc_ids": ["REAL-VL-001"],
            "spec_slugs": ["explicit-comment"],
        }
    ]


@pytest.mark.parametrize(
    "declaration",
    [
        "test.skip('excluded', () => { /* tc: SKIP-VL-001 */ });",
        "it.todo('excluded', () => { /* tc: SKIP-VL-001 */ });",
        "test.skip.each([1])('excluded', () => { /* tc: SKIP-VL-001 */ });",
        "describe.skip('excluded', () => { test('nested', () => { /* tc: SKIP-VL-001 */ }); });",
        "describe.todo('excluded', () => { it('nested', () => { /* tc: SKIP-VL-001 */ }); });",
        (
            "describe.skip.each([1])('excluded', () => { "
            "it('nested', () => { /* tc: SKIP-VL-001 */ }); });"
        ),
    ],
)
def test_explicit_skip_and_todo_exclude_entire_registration(
    tmp_path: Path, declaration: str
) -> None:
    source = _source(tmp_path, "skip.test.ts", declaration)
    assert _bindings(tmp_path, [source]) == []


def test_lexical_shadowing_imports_and_hoisting(tmp_path: Path) -> None:
    imported = _source(
        tmp_path,
        "imports.test.ts",
        """import { test, it } from 'unrelated-library';
import * as unrelated from 'unrelated-library';
import type { test as typeOnly } from 'vitest';
test('fake', () => { /* tc: SHADOW-IMPORT-001 */ });
it('fake', () => { /* tc: SHADOW-IMPORT-002 */ });
unrelated.test('fake', () => { /* tc: SHADOW-IMPORT-003 */ });
typeOnly('fake', () => { /* tc: SHADOW-TYPE-001 */ });
""",
    )
    scoped = _source(
        tmp_path,
        "scope.test.ts",
        """import { test as scenario, describe } from 'vitest';
import * as vt from 'vitest';
describe('suite', () => {
  {
    scenario('shadowed before declaration', () => { /* tc: SHADOW-LOCAL-001 */ });
    const scenario = unrelated;
  }
  {
    vt.test('namespace shadowed', () => { /* tc: SHADOW-NAMESPACE-001 */ });
    const vt = unrelated;
  }
  {
    it('function shadowed', () => { /* tc: SHADOW-FUNCTION-001 */ });
    function it() {}
  }
  try {} catch (test) {
    test('catch shadowed', () => { /* tc: SHADOW-CATCH-001 */ });
  }
  scenario('real alias', () => { /* tc: REAL-ALIAS-001 */ });
});
describe('parameter shadowing', (scenario) => {
  scenario('fake', () => { /* tc: SHADOW-PARAMETER-001 */ });
});
describe('var hoisting', () => {
  test('fake', () => { /* tc: SHADOW-VAR-001 */ });
  if (false) { var test = unrelated; }
});
""",
    )
    assert _bindings(tmp_path, [imported, scoped]) == [
        {
            "nodeid": "scope.test.ts::suite::real alias@19",
            "tc_ids": ["REAL-ALIAS-001"],
            "spec_slugs": [],
        }
    ]


def test_duplicate_titles_paths_and_same_line_have_distinct_identities(
    tmp_path: Path,
) -> None:
    first = _source(
        tmp_path,
        "first/same.test.js",
        """test('same', () => { /* tc: DUP-VL-001 */ });
test('same', () => { /* tc: DUP-VL-002 */ });
test('same', () => {}); test('same', () => {});
""",
    )
    second = _source(
        tmp_path,
        "second/same.test.js",
        "test('same', () => { /* tc: DUP-VL-003 */ });\n",
    )
    bindings = _bindings(tmp_path, [first, second, first])
    assert [binding["nodeid"] for binding in bindings] == [
        "first/same.test.js::same@1",
        "first/same.test.js::same@2",
        "first/same.test.js::same@3",
        "first/same.test.js::same@3:25",
        "second/same.test.js::same@1",
    ]
    assert [binding["tc_ids"] for binding in bindings] == [
        ["DUP-VL-001"],
        ["DUP-VL-002"],
        [],
        [],
        ["DUP-VL-003"],
    ]


def test_titles_are_never_executed_and_options_callback_is_supported(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "dynamic.test.ts",
        """throw new Error('source must never execute');
test(process.exit(99), { timeout: 100 }, () => {
  // tc: STATIC-VL-001
});
""",
    )
    assert _bindings(tmp_path, [source]) == [
        {
            "nodeid": "dynamic.test.ts::process.exit(99)@2",
            "tc_ids": ["STATIC-VL-001"],
            "spec_slugs": [],
        }
    ]


def test_unsupported_indirect_callbacks_do_not_invent_coverage(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "indirect.test.ts",
        """const body = () => { /* tc: INDIRECT-VL-001 */ };
test('indirect', body);
const alias = test;
alias('indirect alias', () => { /* tc: INDIRECT-VL-002 */ });
test.skipIf(condition)('conditional', () => { /* tc: INDIRECT-VL-003 */ });
""",
    )
    assert _bindings(tmp_path, [source]) == []


def test_syntax_error_fails_entire_batch_without_partial_bindings(tmp_path: Path) -> None:
    valid = _source(tmp_path, "valid.test.ts", "test('ok', () => { /* tc: OK-VL-001 */ });")
    invalid = _source(tmp_path, "broken.test.tsx", "test('broken', () => { const view = <div>;\n")
    result = _invoke(tmp_path, [valid, invalid])
    assert result.returncode == 2
    assert result.stdout == ""
    assert "broken.test.tsx:" in result.stderr
    assert "TypeScript" in result.stderr
    assert "語法錯誤" in result.stderr


def test_missing_compiler_is_an_explicit_tool_error(tmp_path: Path) -> None:
    isolated = tmp_path / "isolated-helper.cjs"
    shutil.copyfile(HELPER, isolated)
    source = _source(tmp_path, "missing.test.ts", "test('ok', () => { /* tc: OK-VL-001 */ });")
    result = _invoke(tmp_path, [source], helper=isolated)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "TypeScript 不可用" in result.stderr
    assert str(source) in result.stderr
