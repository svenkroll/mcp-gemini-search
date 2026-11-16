#!/usr/bin/env bash
# Check the Renovate configuration of the repository: the configuration is
# valid and Renovate extracts the dependencies with it without error
# (docs/adr/0011-container-and-ci.md, sections "Single source" and
# "Build policy").
#
# Usage (from any directory inside the repository):
#   scripts/ci/renovate-check.sh
#
# Arguments: none. Any argument is a usage error.
#
# Behavior:
#   1. Validates the arguments before anything else; on a usage error Docker
#      is not called.
#   2. Resolves the repository root from the location of this script
#      (git rev-parse --show-toplevel), so the result is the same from any
#      working directory inside the repository.
#   3. Checks that <root>/renovate.json exists as a file; otherwise prints
#      "renovate.json not found: <root>/renovate.json" on stderr and exits 1
#      without calling Docker.
#   4. Reads the reference of the official Renovate image (tag and digest)
#      from its single source, the service `renovate` in
#      scripts/ci/renovate/compose.yaml, with the tool that owns the file:
#        docker compose --file <root>/scripts/ci/renovate/compose.yaml config --images
#      The output must be exactly one non-empty line; that line is the image
#      reference used below. A failing command or any other output is a
#      Docker failure (exit 1, message on stderr).
#   5. Step 1, the validator:
#        docker run --rm --network none \
#          --volume <root>:/repo:ro --workdir /repo \
#          --env GIT_CONFIG_COUNT=1 \
#          --env GIT_CONFIG_KEY_0=safe.directory \
#          --env GIT_CONFIG_VALUE_0=/repo \
#          <image> renovate-config-validator --strict renovate.json
#   6. Step 2, only after step 1 succeeded, the extraction dry run with the
#      same docker run options and image:
#        ... <image> renovate --platform=local --dry-run=extract
#   Both containers run as the default user of the image. The three
#   GIT_CONFIG_* variables mark /repo as a safe git directory, so the check
#   also runs when the repository files belong to a different user than the
#   user inside the image. These three variables are the only environment
#   passed to the containers: no --env-file, no pass-through form
#   (--env NAME without a value), no token or other secret. No network, the
#   repository is mounted read-only, nothing is written to the repository.
#
# Environment: none is read. Variables of the calling environment (e.g.
#   GITHUB_TOKEN, RENOVATE_TOKEN) never reach the containers.
#
# Output:
#   stdout/stderr: the output of both Renovate steps unchanged, including the
#   validator result and Renovate's "Dependency extraction complete" entry;
#   on failure a line on stderr naming the failed part ("renovate.json not
#   found: ...", "reading the Renovate image failed", "Renovate configuration
#   validation failed" or "Renovate extraction failed").
#   No files are written.
#
# Exit codes:
#   0  both steps succeeded
#   1  renovate.json is missing, the image reference could not be read, a
#      step failed, or Docker failed (including the Docker daemon not being
#      reachable)
#   2  usage error (any argument); "usage: scripts/ci/renovate-check.sh"
#      on stderr
#
# Prerequisites: Docker with Compose v2, git.
set -euo pipefail

echo "not implemented" >&2
exit 1
