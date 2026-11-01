#!/usr/bin/env node
'use strict';

// 只解析 AST，不載入或執行測試。僅支援原地宣告的 callback；不推演 helper、
// 動態別名、skipIf/runIf 或條件運算式。標記須位於 callback 最外層陳述式之間。
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');

const resolutions = new Map();
const compilers = new Map();

function compilerFor(file) {
  const directory = path.dirname(file);
  if (!resolutions.has(directory)) {
    let resolved;
    try {
      resolved = createRequire(file).resolve('typescript');
    } catch (error) {
      if (error.code !== 'MODULE_NOT_FOUND') throw error;
      try {
        resolved = require.resolve('typescript');
      } catch (fallbackError) {
        throw new Error(`TypeScript 不可用：${file}；請在目標專案或 plugins/sdd 安裝 typescript。`, { cause: fallbackError });
      }
    }
    resolutions.set(directory, resolved);
  }
  const resolved = resolutions.get(directory);
  if (!compilers.has(resolved)) compilers.set(resolved, require(resolved));
  return compilers.get(resolved);
}

function bindingsFor(file, root) {
  const ts = compilerFor(file);
  const text = fs.readFileSync(file, 'utf8');
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const options = { noLib: true, noResolve: true, allowJs: true, target: ts.ScriptTarget.Latest };
  // 不解析 import 或讀取專案其他模組；checker 只負責本檔 lexical binding。
  const host = {
    getSourceFile: (name) => name === file ? source : undefined,
    getDefaultLibFileName: () => '',
    writeFile: () => {},
    getCurrentDirectory: () => root,
    getDirectories: () => [],
    fileExists: (name) => name === file,
    readFile: (name) => name === file ? text : undefined,
    getCanonicalFileName: (name) => name,
    useCaseSensitiveFileNames: () => true,
    getNewLine: () => '\n',
  };
  const program = ts.createProgram([file], options, host);
  const diagnostics = program.getSyntacticDiagnostics(source);
  if (diagnostics.length) {
    const diagnostic = diagnostics[0];
    const position = source.getLineAndCharacterOfPosition(diagnostic.start || 0);
    throw new Error(`${file}:${position.line + 1}:${position.character + 1}：TypeScript 語法錯誤：${ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')}`);
  }
  const checker = program.getTypeChecker();
  const bindings = [];
  const identities = new Set();
  const relative = path.relative(root, file).split(path.sep).join('/');

  function unwrap(node) {
    while (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) ||
           ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node) ||
           ts.isSatisfiesExpression(node)) node = node.expression;
    return node;
  }

  function importedName(identifier) {
    const symbol = checker.getSymbolAtLocation(identifier);
    if (!symbol) return ['it', 'test', 'describe'].includes(identifier.text) ? identifier.text : null;
    const declarations = symbol.declarations || [];
    if (declarations.length !== 1) return null;
    const declaration = declarations[0];
    if (ts.isImportSpecifier(declaration)) {
      const clause = declaration.parent.parent;
      const statement = clause.parent;
      if (declaration.isTypeOnly || clause.isTypeOnly || statement.moduleSpecifier.text !== 'vitest') return null;
      const name = (declaration.propertyName || declaration.name).text;
      return ['it', 'test', 'describe'].includes(name) ? name : null;
    }
    if (ts.isNamespaceImport(declaration)) {
      const clause = declaration.parent;
      return !clause.isTypeOnly && clause.parent.moduleSpecifier.text === 'vitest' ? 'namespace' : null;
    }
    return null;
  }

  function callable(expression) {
    expression = unwrap(expression);
    if (ts.isIdentifier(expression)) {
      const kind = importedName(expression);
      return kind ? { kind, disabled: false, each: false, factory: false } : null;
    }
    if (ts.isPropertyAccessExpression(expression) && !expression.questionDotToken) {
      const base = callable(expression.expression);
      if (!base) return null;
      const name = expression.name.text;
      if (base.kind === 'namespace') {
        return ['it', 'test', 'describe'].includes(name) ? { ...base, kind: name } : null;
      }
      if (base.each || base.factory) return null;
      if (name === 'skip' || name === 'todo') return { ...base, disabled: true };
      if (name === 'each') return { ...base, each: true };
      if (['only', 'concurrent', 'sequential', 'fails'].includes(name)) return base;
      return null;
    }
    if ((ts.isCallExpression(expression) && !expression.questionDotToken) || ts.isTaggedTemplateExpression(expression)) {
      const base = callable(ts.isCallExpression(expression) ? expression.expression : expression.tag);
      return base && base.each && !base.factory ? { ...base, each: false, factory: true } : null;
    }
    return null;
  }

  function commentsIn(callback) {
    const tcIds = [];
    const specSlugs = [];
    if (!ts.isBlock(callback.body)) return { tc_ids: tcIds, spec_slugs: specSlugs };
    const ranges = new Map();
    function collect(position) {
      for (const range of [
        ...(ts.getLeadingCommentRanges(text, position) || []),
        ...(ts.getTrailingCommentRanges(text, position) || []),
      ]) {
        if (range.pos > callback.body.getStart(source) && range.end < callback.body.end) ranges.set(range.pos, range);
      }
    }
    collect(callback.body.statements.pos);
    collect(callback.body.statements.end);
    for (const statement of callback.body.statements) {
      collect(statement.pos);
      collect(statement.end);
    }
    for (const range of [...ranges.values()].sort((a, b) => a.pos - b.pos)) {
      const comment = text.slice(range.pos + 2, range.kind === ts.SyntaxKind.MultiLineCommentTrivia ? range.end - 2 : range.end);
      for (const raw of comment.split(/\r?\n/)) {
        const line = raw.replace(/^\s*\* ?/, '').trim();
        const tc = /^tc:\s*(.+)$/.exec(line);
        if (tc) tcIds.push(...(tc[1].match(/\b[A-Z][A-Z0-9]*(?:-[A-Za-z0-9]+)+\b/g) || []));
        for (const spec of line.matchAll(/(?<![A-Za-z])spec:\s+[A-Za-z0-9][A-Za-z0-9-]*#([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)/g)) specSlugs.push(spec[1]);
      }
    }
    return { tc_ids: tcIds, spec_slugs: specSlugs };
  }

  function titleOf(node) {
    node = unwrap(node);
    return ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ? node.text : node.getText(source);
  }

  function visit(node, suites) {
    // 不把未呼叫 helper、hook 或任意 callback 內的 test 宣告視為註冊。
    if (ts.isFunctionLike(node) || ts.isClassLike(node)) return;
    if (ts.isCallExpression(node) && !node.questionDotToken) {
      const registration = callable(node.expression);
      if (registration && registration.kind !== 'namespace' && !registration.each) {
        if (registration.disabled) return;
        const callbackArgument = node.arguments[1] && unwrap(node.arguments[1]);
        const optionsCallback = node.arguments[2] && unwrap(node.arguments[2]);
        const isCallback = (value) => value && (ts.isArrowFunction(value) || ts.isFunctionExpression(value));
        const callback = isCallback(callbackArgument) ? callbackArgument : isCallback(optionsCallback) ? optionsCallback : null;
        if (!callback || !node.arguments[0]) return;
        const title = titleOf(node.arguments[0]);
        if (registration.kind === 'describe') {
          visit(callback.body, [...suites, title]);
        } else {
          const position = source.getLineAndCharacterOfPosition(node.getStart(source));
          let nodeid = [relative, ...suites, `${title}@${position.line + 1}`].join('::');
          // 同一行重複標題另以欄位區分，通常情況維持 @line 格式。
          if (identities.has(nodeid)) nodeid += `:${position.character + 1}`;
          identities.add(nodeid);
          bindings.push({ nodeid, ...commentsIn(callback) });
        }
        return;
      }
    }
    ts.forEachChild(node, (child) => visit(child, suites));
  }

  visit(source, []);
  return bindings;
}

try {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  if (!request || !Array.isArray(request.files) || typeof request.repo_root !== 'string' ||
      !path.isAbsolute(request.repo_root) || request.files.some((file) => typeof file !== 'string' || !path.isAbsolute(file))) {
    throw new Error('輸入須為 {files: [絕對路徑], repo_root: 絕對路徑}。');
  }
  const bindings = [];
  for (const file of new Set(request.files)) bindings.push(...bindingsFor(file, request.repo_root));
  process.stdout.write(JSON.stringify(bindings));
} catch (error) {
  process.stderr.write(`vitest_trace：${error.message}\n`);
  process.exitCode = 2;
}
