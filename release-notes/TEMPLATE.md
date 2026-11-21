<!--
Release notes template. Copy this file to release-notes/<version>.md (for example
release-notes/1.8.0.md) and fill it in. The structure is fixed and checked by the release
guard (#408):

- The summary paragraph and "### Highlights" are required.
- The other sections are optional. Leave a section out completely when it has nothing
  to say; never leave it empty and never write "None".
- Keep the sections in this order and keep the heading texts exactly as written here.
  No other headings.
- Delete every comment, including this one, before you commit the file.

The file is printed above the generated "### Features" and "### Bug Fixes" lists, in the
GitHub release and under the version heading in CHANGELOG.md. That is why the sections
use "###".
-->

<!--
Summary (required): one paragraph of 2 to 3 sentences, no heading. Say what this release
is about for the user: what they can do now that they could not do before.
-->
Labelyard x.y.0 ...

### Highlights

<!--
Highlights (required): 4 to 7 items. Each item is one line in this form:
- **Bold lead.** One or two sentences on what the user gets, not how it was built. ([#123](https://github.com/strausmann/labelyard/issues/123))
Every item links at least one closed issue of the milestone; several issues are separated
by ", ". Optionally one screenshot after the list, as an absolute URL so it shows in the
GitHub release too:
![Short description](https://raw.githubusercontent.com/strausmann/labelyard/main/docs/screenshots/<file>.png)
-->
- **...** ... ([#123](https://github.com/strausmann/labelyard/issues/123))

### Upgrade notes

<!--
Upgrade notes (optional): only when there is something to do or to know before
upgrading: a migration, a changed default, a renamed setting or image, a changed API
answer, a limit on rolling back. 1 to 5 items, same form as the highlights (bold lead,
one or two sentences). Link the upgrade page on labelyard.app when there is one.
Leave the section out when nothing changes for an operator.
-->
- **...** ...

### Hardware and compatibility

<!--
Hardware and compatibility (optional): printers, tapes, rolls and sheet types that are new,
newly tested or corrected in this release. 1 to 5 items, same form as the highlights,
each with an issue link. Only list what was tested; untested support says so.
-->
- **...** ... ([#123](https://github.com/strausmann/labelyard/issues/123))

### Thanks

<!--
Thanks (optional): community members who tested, reported or contributed, by GitHub
handle (@handle), with what they did in a few words. No real names, e-mail addresses or
other personal data unless the person asked for it.
-->
- @... for ...
