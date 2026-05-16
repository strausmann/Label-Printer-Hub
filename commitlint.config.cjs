/* commitlint enforces Conventional Commits at PR/CI time. */

module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      [
        'feat',
        'fix',
        'perf',
        'docs',
        'style',
        'refactor',
        'test',
        'chore',
        'ci',
        'build',
        'revert',
      ],
    ],
    'scope-enum': [
      1,
      'always',
      [
        'printer-backends',
        'printer-models',
        'queue',
        'status',
        'api',
        'ui',
        'webhook',
        'docker',
        'ci',
        'examples',
        'docs',
        'integration',
        'pwa',
        'security',
        'release',
        'deps',
        'deps-dev',
      ],
    ],
    'subject-case': [2, 'never', ['upper-case', 'pascal-case', 'start-case']],
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.'],
    // 120 instead of the conventional-commits default of 100. Dependabot's
    // grouped/directory-scoped PR titles (e.g. "chore(deps): bump X from 1.2 to
    // 1.3 in /frontend in the go-minor-and-patch group") routinely run 100-110
    // chars. Tightening to 100 produced no improvement in human-authored
    // commits but did block legitimate Dependabot PRs. 120 keeps the bound
    // tight enough to discourage rambling subjects while accommodating the
    // tooling reality.
    'header-max-length': [2, 'always', 120],
  },
};
