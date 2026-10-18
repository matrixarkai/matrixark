# Contributing to MatrixArk

Thanks for your interest in improving MatrixArk. Issues, discussion and pull requests
are all welcome, from anyone. The project is Apache-2.0 and open to the world; you do
not need to be affiliated with anything to contribute.

## Ground rules

- **Validation happens before the write, not after.** The public service raises
  `MatrixArkValidationError` before anything reaches the serving store. If a change adds
  a field, add its check at the same boundary — a bad agent input that gets stored
  becomes replayable context, and then it is everyone's problem.
- **The fast tests must not reach the network.** Default providers are deterministic
  local stand-ins precisely so that `python -m unittest` works on a laptop with no
  model downloads. A test that needs a real model belongs behind
  `MATRIXARK_ALLOW_MODEL_DOWNLOAD` and the Docker flow, not in the default suite.
- **Determinism is a feature of the test suite.** If a test depends on wall-clock time,
  dictionary ordering, or a float comparison without a tolerance, it will fail for
  somebody else on a different machine. Pin the clock, sort the collection, state the
  tolerance.
- **One serving store.** Events, nodes, chunks, indexes, embeddings and replay all go
  through the TemporalStore adapter protocol. Adding a second place for serving state to
  live is the change most likely to be sent back.
- **Raw bytes stay where they are.** Resources are referenced by `raw_uri`. Copying
  original files into the serving store is not an optimisation, it is a second copy to
  keep consistent.
- **Tenancy is not optional.** Anything that reads or writes serving state takes a
  `tenant_id` and scopes by it. A query that can see another tenant's rows is a bug of
  the most serious kind, so say in the pull request how a new path is scoped.

## Before you open a pull request

Run the fast suite:

```bash
python -m unittest discover -s matrixark/tests -v
```

And the end-to-end suites, if you touched the runtime:

```bash
python -m unittest discover -s tests -v
```

Then say in the description **what you ran and what it printed**. A description that
says the tests pass, without the counts, is the one thing a reviewer cannot check.

If a change is a performance claim, give the measurement and the shape of the thing you
measured — how many records, how many tenants, which provider. A speed-up that only
holds at one record count is worth knowing about, but only if the record count is
stated.

## Style

Match the file you are editing. The codebase prefers:

- descriptive test names that read as sentences about behaviour, rather than
  `test_foo_2`
- small modules with a single responsibility over a utilities grab-bag
- explicit arguments over configuration read from the environment deep inside a call
- comments that say *why*, where the code already says *what*

## Reporting a problem

Open an issue. The things that make a report actionable:

- what you ran, verbatim, and what happened
- what you expected instead
- the Python version and whether you were on the default providers or Docker
- the smallest input that still shows it

A report with a reproduction is worth more than a report with a diagnosis, and you are
welcome to send both.

## Security

If you believe you have found a vulnerability — anything that lets one tenant read or
write another's data, or that lets untrusted input execute — please report it privately
to the maintainers rather than opening a public issue, and give us a chance to ship a
fix first.

## License

By contributing, you agree that your contributions are licensed under the Apache
License 2.0, the same terms as the rest of the project.
