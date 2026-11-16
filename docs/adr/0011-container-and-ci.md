---
status: proposed
date: 2026-11-16
decision-makers: Sven Kroll
---

# 0011 Container and CI

## Context and Problem Statement

The first container job (#11, PR #46) put about 160 lines of shell and an
embedded Python stub into `ci.yml`, built every image twice without a cache,
emulated arm64, read the Caddy image from `compose.yaml` with a regex and ran a
test stub inside the production image. Most of it followed rules that were
written into that single ticket. Rules for images and CI need one permanent
place, so that every new image or job follows them without each ticket
restating them.

## Considered Options

1. Rules per ticket, as in #11.
2. A ticket template with a non-functional section.
3. One ADR for all images and CI jobs, referenced from `AGENTS.md`.

## Decision

**Option 3**. The rules apply to every image and every CI job in the
repository.

### Structure

- Workflows only orchestrate. Logic beyond a few lines lives in executable Bash
  scripts under `scripts/ci/`, starting with `set -euo pipefail`.
- Every script runs locally with Docker as the only prerequisite besides the
  project setup (`make install`).
- The `container` job stays in `.github/workflows/ci.yml`.

### Single source

- Every version, digest and checksum has exactly one source.
- Values are read with the tool that owns the file, for example
  `docker compose config --images`, never with a regular expression over YAML.
- uv has one source: the `uv` stage of the `Dockerfile`. CI jobs that need uv
  export it with `scripts/ci/export-uv.sh`.

### Pinning

| What | Pinned by |
| --- | --- |
| GitHub Actions | 40-character commit SHA plus a version comment |
| Downloaded binaries and installers | SHA-256 |
| Container images | digest |

### Allowed actions

- `actions/*`
- `docker/setup-buildx-action`
- `docker/build-push-action`

Any other action requires a change of this ADR.

### Build policy

- Pull requests and pushes to `main` never push images. Only the release
  workflow pushes (section "Release").
- Image builds use `docker/build-push-action` with the GitHub Actions cache.
  The image used for scan and tests is the one that was built, not a second
  build.
- What runs depends on the changed paths, detected by a script under
  `scripts/ci/`, not by an additional action:

| Step | Runs when these paths change |
| --- | --- |
| linux/amd64 build, image scan, smoke test | `Dockerfile`, `.dockerignore`, `pyproject.toml`, `uv.lock`, `src/` |
| linux/arm64 build, natively on `ubuntu-24.04-arm` | `Dockerfile`, `.dockerignore`, `uv.lock` |
| proxy test | `Caddyfile`, `compose.yaml` |
| every step above | `scripts/ci/` (including `scripts/ci/proxy-stub/`), `.github/workflows/` |

- A push to `main` runs every step.
- Without relevant changes the `container` job finishes successfully without
  building, so it can remain a required check.
- No emulation: arm64 is built on the native runner.
- Exporting the `uv` stage with the local exporter
  (`scripts/ci/export-uv.sh`) is not an image build and needs neither
  `docker/build-push-action` nor a cache.

### Image scan

- Trivy fails the job on CRITICAL findings, whether a fix exists or not.
- HIGH findings are reported without failing the job.
- Exceptions only in `.trivyignore`: one entry per CVE with a reason and a
  review date, added by the project owner.

### Test isolation

Test helpers such as stubs and fake backends never run inside the production
image. They use their own image, pinned by digest.

### Release

A release is a version tag set by the project owner. The workflow
`.github/workflows/release.yml` builds, checks and publishes the image.

- **Trigger:** only a pushed tag `v*`. No manual, branch or pull request
  triggers.
- **Tag check** before any build; on failure nothing is built or pushed:
  - SemVer with `v` prefix and without build metadata (`+...`), e.g. `v1.0.0`
    or `v1.0.0-rc.1`. Build metadata is rejected because image tags cannot
    contain `+`.
  - The tag version equals `project.version` in `pyproject.toml` after
    PEP 440 normalization: tag `v1.0.0-rc.1` matches `1.0.0rc1`.
  - The tagged commit is on `main`.
- **Build:** one job per architecture on a native runner, no emulation. Each
  job pushes its image by digest, without a tag, to
  `ghcr.io/svenkroll/mcp-gemini-search`.
- **Checks** with the same scripts as the `container` job: Hadolint on the
  `Dockerfile` before the build; image scan and smoke test on the pushed
  digest, pulled back from the registry, per architecture. The rules of
  section "Image scan" apply.
- **Publish:** only when every architecture passed, one job creates the
  manifest list from the checked digests (`docker buildx imagetools create`)
  with exactly two tags: the version without `v` (e.g. `1.0.0`) and the full
  commit SHA. No `latest`, no floating tags. Pre-releases are published the
  same way.
- **Failed runs** leave untagged digests in GHCR; the project owner deletes
  them manually.
- **Labels:** `org.opencontainers.image.source` (links the package to the
  repository before the first push), `org.opencontainers.image.version`,
  `org.opencontainers.image.revision`.
- **Attestations:** none (no provenance, no SBOM) until signing and SBOM are
  decided.
- **Permissions:** the release workflow has only `contents: read` and
  `packages: write`. Login with `GITHUB_TOKEN` via `docker login` in a script,
  no additional action.
- **Visibility:** GHCR does not take over the repository visibility. The
  project owner sets the package to public once, after the first release.
- Deployment is not part of this ADR.

### Runtime budget

A full run of the `container` job on `main` with a warm cache takes at most
15 minutes. Pull requests stay below that through the build policy.

## Consequences

- Good: Tickets for images and CI name what is built and reference this ADR;
  the rules no longer depend on how a ticket is worded.
- Good: Every CI step can be reproduced locally with one command.
- Good: A change to the CI scripts or workflows runs every container step in
  its pull request, so a broken script or job fails before it reaches `main`.
- Good: No emulation, one build per architecture and a shared cache keep the
  job short; documentation-only changes do not build at all.
- Good: The image scan does not block pull requests on HIGH findings that
  appear in the vulnerability database independently of the change.
- Good: The published image is exactly the digest that was scanned and
  smoke-tested on its own architecture; tags are set only after every check
  passed.
- Good: uv has one source that a dependency update tool can maintain, and no
  checksum is maintained by hand.
- Good: A release cannot publish a version that differs from
  `pyproject.toml` or a commit outside `main`.
- Bad: The `check` job depends on Docker on the runner and pulls the uv image
  on every run.
- Bad: Two third-party actions from Docker are part of the supply chain.
- Bad: A failed release leaves untagged digests in GHCR that the project
  owner removes manually.
- Bad: The package visibility needs one manual step after the first release.
- Bad: An unfixed CRITICAL finding blocks every image change until the project
  owner adds an exception.
- Bad: Every change under `scripts/ci/` or `.github/workflows/` runs the full
  `container` job, including both builds, even when it touches a single script.
- Bad: An arm64-only problem caused by a change under `src/` shows up only on
  `main`.

## Open

- actionlint and zizmor for workflow files, Hadolint without Docker locally
  (`docs/techdebt.md`).
- Signing and SBOM for published images.
- Deployment of releases.

## More Information

- [GitHub Actions cache limits](https://docs.github.com/en/actions/reference/limits)
- [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- ADR 0002, ADR 0008, ADR 0010
