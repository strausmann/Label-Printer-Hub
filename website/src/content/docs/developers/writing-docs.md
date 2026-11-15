---
title: Writing docs
description: The house style for the Labelyard docs, the glossary that fixes the terms, and the prose checks that run on every pull request.
---

Every page here follows one rule:

> Write for the reader: what they want to do, then how. Short sentences, one idea each. German is written natively, not translated word for word, and addresses the reader as „du“. Use the glossary term for every concept, in both languages. A change to the docs is complete only with English and German in the same pull request.

## What the rule means

- **Start with the goal.** Open a page, and each section, with what the reader wants to do. Then give the steps.
- **One idea per sentence.** Aim for 30 words or fewer in English and 25 in German. A longer sentence is usually two.
- **Write German natively.** Do not translate English word for word. Say it the way a German speaker would explain it. Address the reader as „du“ and use real umlauts: ä, ö, ü, ß.
- **Use the glossary term.** Each concept has one English and one German term in the [glossary](/using/glossary/). Do not mix in a synonym or an English word on a German page.
- **Ship both languages together.** A page under `website/src/content/docs/` changes in English and in German (`de/`, same slug) in the same pull request. The `website / locale parity` check fails otherwise.

## The glossary

`docs/glossary.toml` is the single source. It lists each concept once, in both languages, with a short meaning and the spellings to avoid. Three things are generated from it, so they cannot drift apart:

- the two glossary pages of this website,
- the Vale rules and vocabularies in `.vale/`,
- the check of the interface texts in `frontend/src/i18n/locales/`.

To add or change a term, edit the TOML file and run:

```bash
python3 scripts/glossary.py write
```

Commit the generated files with it. CI fails on generated files that are out of date.

## The prose checks

The `prose` workflow runs [Vale](https://vale.sh/) on `README.md`, `CONTRIBUTING.md`, `docs/` and this website. Code blocks are not checked. Two levels matter:

| Level | What it catches | Effect |
|---|---|---|
| Error | The former product name. A rejected glossary term, such as `API-Key` for “API key”. | Fails the check |
| Warning | A rejected term that has a substitute, filler words, a sentence over the limit. | Reported only |
| Suggestion | Weasel words and wordy phrases. | Reported only |

To run it on your machine:

```bash
scripts/vale_setup.sh
python3 scripts/vale_scope.py | xargs .vale/bin/vale
```

`vale_setup.sh` installs the pinned Vale release and checks its checksum. Add `--minAlertLevel=error` to see only what fails CI.

A page that has to name the former product, such as the migration guide, has its own section in `.vale.ini`. Do not add `Label Printer Hub` anywhere else, except as the subtitle next to Labelyard.
