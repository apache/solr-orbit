# Changelog fragments

One Markdown file per PR, named `<PR number>.<type>.md`. `make changelog` folds them into
[CHANGELOG.md](../CHANGELOG.md) at release time and deletes them.

Write one or two sentences for a user of Solr Orbit, no leading bullet or PR number, ending with
the author in parentheses. `@jdoe` is a GitHub handle, `jdoe` a nick or Apache id, `John Doe`
a full name. Several authors: `(@jdoe, @asmith)`.

```markdown
`solr-orbit stop` no longer fails with a missing `metrics_store_class` attribute. (@jdoe)
```

| type         | use for                                                |
|--------------|--------------------------------------------------------|
| `breaking`   | changes that require users to adapt workloads or flags |
| `added`      | new features, commands, flags, telemetry devices       |
| `changed`    | changes to existing behaviour that are not breaking    |
| `deprecated` | features that still work but will be removed           |
| `removed`    | features that are gone                                 |
| `fixed`      | bug fixes                                              |
| `security`   | security fixes                                         |
| `docs`       | documentation changes worth announcing                 |

Refactoring, test-only and CI changes need no fragment. A fragment without a PR is named
`+<slug>.<type>.md` and renders without a link.

```bash
make changelog-draft   # preview the pending release notes
```
