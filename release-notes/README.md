<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Release notes

This folder holds the maintainer-written part of the release notes. Every minor and major release must have a file `release-notes/<version>.md`, for example `release-notes/1.8.0.md`. It is committed on the milestone branch before the milestone is merged. The release prints it above the generated lists of features and fixes, in the GitHub release and in `CHANGELOG.md` (introduced by [#408](https://github.com/strausmann/labelyard/issues/408)). Patch releases do not need one.

Every file must follow [`TEMPLATE.md`](TEMPLATE.md): copy it, fill it in and delete its comments. The summary paragraph and `### Highlights` with 4 to 7 items, each with an issue link, are required and come first. Optional sections must be ones the template lists, in its order and with its heading texts. No other headings are allowed. The release guard (#408) checks the file and refuses a release whose file is missing or does not match. Write about what the user gets, not how it was built, without superlatives or emojis. Every highlight must trace to a closed issue of the milestone. No personal data: no real names, e-mail addresses, hostnames or IP addresses.
