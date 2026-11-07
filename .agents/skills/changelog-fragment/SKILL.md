---
name: changelog-fragment
description: Draft the changelog fragment (changelog.d/<PR>.<type>.md) for the changes on the current branch. Use when a PR is ready and has no fragment yet, or when a reviewer asks for one.
---

# Changelog fragment

Format, types and attribution rules are in `changelog.d/README.md`; read it first.

## Steps

1. Find the `apache/solr-orbit` remote with `git remote -v`; it is often `upstream`, not
   `origin`. Fetch it. Without such a remote, use the PR's base from
   `gh pr view --json baseRefName` or ask.
2. Read `git log <remote>/main..HEAD --oneline` and the diff of the files that change
   behaviour. Skip tests and CI unless they are the whole change.
3. If the change is not user-visible (refactoring, tests, CI), say so and stop.
4. Pick the type. Anything that makes users adapt a workload, flag or config file is
   `breaking`, however small.
5. PR number: `gh pr view --json number -q .number`. Without a PR, use `+<slug>.<type>.md`
   and tell the author to rename it.
6. Write one or two sentences for a user, naming the command, flag or feature they would
   recognise, in backticks.
7. Append the author: `(@login)` from `gh pr view --json author -q .author.login` unless the
   author prefers a nick or full name.
8. Show the rendered line from `make changelog-draft`.

## Examples

`changelog.d/124.fixed.md`

```markdown
`solr-orbit stop` works again; it failed with a missing `metrics_store_class` attribute. (@jdoe)
```

`changelog.d/115.changed.md`

```markdown
The `optimize` operation follows Solr's merge policy by default instead of forcing a single segment. Pass `max-num-segments` to restore the old behaviour. (@jdoe)
```
