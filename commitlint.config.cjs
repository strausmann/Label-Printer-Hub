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
      ],
    ],
    'subject-case': [2, 'never', ['upper-case', 'pascal-case', 'start-case']],
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.'],
    'header-max-length': [2, 'always', 100],
  },
};
