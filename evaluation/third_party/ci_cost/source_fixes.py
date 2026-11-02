"""Reviewed source-level correctness fixes for pinned ci-cost v1.0.0.

These modify upstream TypeScript *before it is compiled*. They never modify
candidate workflow YAML after generation. Each replacement is exact-match and
fails closed if the pinned upstream source is not what we reviewed.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

from evaluation.setup_node_compatibility import compatible_setup_node_refs

UPSTREAM_COMMIT = "e3722ea83da600bebac9ad21ec52490df824eb5c"
FIX_REVISION = "cloudtune-ci-cost-npm-download-v4-compatibility"

_OLD_CACHE = r"""function injectCacheStep(
  content: string,
  pmName: string,
  cacheYaml: string
): string {
  // Find the install step and inject cache before it
  const patterns: Record<string, RegExp> = {
    npm: /^(\s+)-\s*(name:.*\n\s+run:.*npm\s+(ci|install))/m,
    yarn: /^(\s+)-\s*(name:.*\n\s+run:.*yarn\s+install)/m,
    pnpm: /^(\s+)-\s*(name:.*\n\s+run:.*pnpm\s+install)/m,
    pip: /^(\s+)-\s*(name:.*\n\s+run:.*pip.*install)/m,
    cargo: /^(\s+)-\s*(name:.*\n\s+run:.*cargo\s+(build|test))/m,
  };

  const pattern = patterns[pmName];
  if (!pattern) return content;

  return content.replace(pattern, `${cacheYaml}\n$1- $2`);
}"""
_NEW_CACHE = r"""function injectCacheStep(
  content: string,
  pmName: string,
  cacheYaml: string
): string {
  // Preserve indentation and existing comments instead of hardcoding six
  // spaces (which previously produced malformed YAML for nested steps).
  const commands: Record<string, RegExp> = {
    npm: /\bnpm\s+(?:ci|install)\b/,
    yarn: /\byarn\s+install\b/,
    pnpm: /\bpnpm\s+install\b/,
    pip: /\bpip\d*\s+install\b/,
    cargo: /\bcargo\s+(?:build|test)\b/,
  };
  const command = commands[pmName];
  if (!command) return content;
  const newline = content.includes('\r\n') ? '\r\n' : '\n';
  const lines = content.split(/\r?\n/);
  const yamlLines = cacheYaml.split(/\r?\n/);
  const firstIndent = Math.min(...yamlLines.filter((line) => line.trim()).map(
    (line) => /^ */.exec(line)?.[0].length ?? 0));
  for (let i = 0; i < lines.length; i++) {
    const header = /^( *)- (name:.*|run:.*)$/.exec(lines[i] ?? '');
    if (!header) continue;
    const depth = header[1]?.length ?? 0;
    const run = header[2]?.startsWith('run:')
      ? /^run:\s*(.*)$/.exec(header[2])
      : new RegExp(`^ {${depth + 2}}run:\\s*(.*)$`).exec(lines[i + 1] ?? '');
    if (!run || !command.test(run[1] ?? '')) continue;
    const formatted = yamlLines.map((line) => line.trim()
      ? ' '.repeat(depth) + line.slice(firstIndent) : line);
    lines.splice(i, 0, ...formatted);
    return lines.join(newline);
  }
  return content;
}"""

_OLD_SHALLOW = r"""function addShallowClone(content: string): string {
  return content.replace(
    /(uses:\s*actions\/checkout@v\d+)(\s*\n)(?!\s+with:)/g,
    `$1$2        with:\n          fetch-depth: 1\n`
  );
}"""
_NEW_SHALLOW = r"""function addShallowClone(content: string): string {
  // Checkout v4 already fetches one commit by default. Only change an
  // explicit full-history fetch (depth 0), retaining the source indentation.
  const newline = content.includes('\r\n') ? '\r\n' : '\n';
  const lines = content.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const checkout = /^( *)- uses:\s*actions\/checkout@v\d+\s*$/.exec(lines[i] ?? '');
    if (!checkout) continue;
    const indent = checkout[1]?.length ?? 0;
    if (!new RegExp(`^ {${indent + 2}}with:\\s*$`).test(lines[i + 1] ?? '')) continue;
    for (let j = i + 2; j < lines.length; j++) {
      const line = lines[j] ?? '';
      if (!line.trim() || /^\s*#/.test(line)) continue;
      const key = new RegExp(`^( {${indent + 4}}fetch-depth:\\s*)0(\\s*(?:#.*)?)$`).exec(line);
      if (key) {
        lines[j] = `${key[1]}1${key[2] ?? ''}`;
        return lines.join(newline);
      }
      if ((/^ */.exec(line)?.[0].length ?? 0) <= indent + 2) break;
    }
  }
  return content;
}"""

_OLD_FAILFAST = r"""function enableFailFast(content: string): string {
  return content.replace(/(\s+fail-fast:\s*false)/g, '$1  # TODO: consider removing this');
}"""
_NEW_FAILFAST = r"""function enableFailFast(content: string): string {
  return content.replace(/^([ \t]*fail-fast:[ \t]*)false([ \t]*(?:#.*)?)$/gm,
    '$1true$2');
}"""


_OLD_OUTPUT_GUARD = """    // Add optimization header comment
    const header = `# Optimized by ci-cost (https://github.com/mariotavarez/ci-cost)"""
_NEW_OUTPUT_GUARD = """    // Fail before writing if a transformation produces invalid YAML.
    // This protects all candidate types, rather than repairing broken output.
    try {
      const parsed = yaml.load(optimizedContent) as Record<string, unknown> | null;
      if (!parsed || typeof parsed !== 'object' || !parsed['jobs']) {
        throw new Error('missing jobs mapping');
      }
    } catch (err) {
      throw new Error(`Invalid generated workflow ${workflow.fileName}: ${(err as Error).message}`);
    }

    // Add optimization header comment
    const header = `# Optimized by ci-cost (https://github.com/mariotavarez/ci-cost)"""

_OLD_SHALLOW_CHECK = "if (fetchDepth === undefined && !needsFullHistory) {"
_NEW_SHALLOW_CHECK = "if ((fetchDepth === 0 || fetchDepth === '0') && !needsFullHistory) {"

_OLD_NPM_PROPOSAL = r"""        optimizedContent = injectCacheStep(
          optimizedContent,
          'npm',
          `      - name: Cache node_modules
        uses: actions/cache@v4
        with:
          path: node_modules
          key: \${{ runner.os }}-node-\${{ hashFiles('**/package-lock.json') }}
          restore-keys: |
            \${{ runner.os }}-node-`
        );"""
_NEW_NPM_PROPOSAL = r"""        // Adapted baseline: cache npm downloads through the existing
        // setup-node action, in the recommended job only. Never cache installed
        // artifacts or change action refs, commands, or other action inputs.
        const doc = yaml.load(optimizedContent) as {
          jobs: Record<string, {steps?: Array<{
            uses?: string; with?: Record<string, unknown>;
          }>}>;
        };
        const steps = rec.affectedJob ? doc.jobs[rec.affectedJob]?.steps : undefined;
        const refs = new Set(__SETUP_NODE_RELEASE_REFS__);
        const setup = steps?.find((step) => step.uses && refs.has(step.uses));
        if (setup?.with?.['node-version'] &&
            !('cache' in setup.with) && !('cache-dependency-path' in setup.with)) {
          setup.with['cache'] = 'npm';
          optimizedContent = yaml.dump(doc, {lineWidth: -1, noRefs: true});
        }"""
_NEW_NPM_PROPOSAL = _NEW_NPM_PROPOSAL.replace(
    "__SETUP_NODE_RELEASE_REFS__", json.dumps(sorted(compatible_setup_node_refs())))

_OLD_CONCURRENCY_APPLY = "        optimizedContent = addConcurrencyGroup(optimizedContent, workflow.name ?? '');"
_NEW_CONCURRENCY_APPLY = """        // npm cache serialization must not make an unrelated transformation
        // newly applicable to source syntax the upstream helper did not handle.
        if (addConcurrencyGroup(workflow.raw, workflow.name ?? '') !== workflow.raw) {
          optimizedContent = addConcurrencyGroup(optimizedContent, workflow.name ?? '');
        }"""

REPLACEMENTS = {
    "src/optimizer.ts": ((_OLD_CACHE, _NEW_CACHE),
                         (_OLD_SHALLOW, _NEW_SHALLOW),
                         (_OLD_FAILFAST, _NEW_FAILFAST),
                         (_OLD_OUTPUT_GUARD, _NEW_OUTPUT_GUARD),
                         (_OLD_NPM_PROPOSAL, _NEW_NPM_PROPOSAL),
                         (_OLD_CONCURRENCY_APPLY, _NEW_CONCURRENCY_APPLY)),
    "src/checks/misc.ts": ((_OLD_SHALLOW_CHECK, _NEW_SHALLOW_CHECK),),
}


def fix_identity() -> str:
    """Hash the complete fix specification for recorded evaluation provenance."""
    parts = [FIX_REVISION]
    for path, changes in sorted(REPLACEMENTS.items()):
        parts.append(path)
        parts.extend(before + "\n" + after for before, after in changes)
    return sha256("\n".join(parts).encode("utf-8")).hexdigest()


def corrected_sources(root: Path) -> dict[str, bytes]:
    """Compute fixed TypeScript without modifying the checkout on failure."""
    results: dict[str, bytes] = {}
    for path, changes in REPLACEMENTS.items():
        source = (root / path).read_text(encoding="utf-8")
        for old, new in changes:
            if source.count(old) != 1:
                raise ValueError(f"Unrecognized pinned upstream source: {path}")
            source = source.replace(old, new)
        results[path] = source.encode("utf-8")
    return results
