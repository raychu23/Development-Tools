# TypeScript code graph with the Compiler API

For a deterministic "current layer": files, top-level symbols, imports, calls, each with file:line@commit.

## Recipe

- `ts.findConfigFile` + `parseJsonConfigFileContent` for compiler options; `ts.sys.readDirectory(src, ['.ts','.tsx'])` as root names; `createProgram` + `getTypeChecker`.
- Symbols: walk top-level statements (functions, classes + members, interfaces, types, enums, variable decls; arrow/function initialisers count as functions). Keep `line`, `end`, `exported`, and a body hash (for stale-explanation cache keys).
- Imports: `ImportDeclaration` / `ExportDeclaration` / dynamic `import()`; resolve with `ts.resolveModuleName`; keep `typeOnly` (clause-level `isTypeOnly`, or every named element type-only) so drift rules can ignore them.
- Calls: `CallExpression`, `NewExpression`, JSX tags; for property access use the `.name` node. `checker.getSymbolAtLocation`; if it's an alias, `getAliasedSymbol` so calls through barrels/re-exports land on the real declaration; owner = nearest enclosing indexed declaration.
- Record timing (program vs walk) and the commit + dirty flag in the output.

## Traps

- **Calls through interface/type members** (`ctx.run()` where `run` is declared on `interface Ctx`) resolve to the interface declaration. Recording them as "calls Ctx" creates many wrong edges; skip edges whose target is an interface or type alias and count them separately.
- Most identifier calls resolve outside the project (libs, builtins, locals): label them non-project, not "unresolved".
- Embedding source text in browser data makes it third-party content: gitignore the data dir.
- Validate by sampling: an edge's line should contain the callee name; a remaining ~1-2% miss is multi-line call chains (`a.b\n.c()`), not wrong edges.
