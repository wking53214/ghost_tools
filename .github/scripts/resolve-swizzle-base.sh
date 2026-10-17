#!/usr/bin/env bash
# Decide which revision the swizzle/assay gate compares this change against.
#
# Usage: resolve-swizzle-base.sh GHOST_TOOLS_DIR
# Environment: EVENT (github.event_name), BEFORE (github.event.before).
#
# Exit codes, each of which is an outcome the job reports in words:
#   0  stdout is the base revision (a full commit SHA). Run the gate against it.
#   3  the very first commit of the repository: there is nothing to compare
#      against and nothing to regress from. ALLOWED, and announced with a
#      ::warning:: so it is visible on the run. This is the only skip.
#   1  no base could be determined where one must exist (a pull request whose
#      merge commit has no first parent, a push whose previous head is
#      unreachable or absent on a repository that has history, an event this
#      gate does not know). The gate FAILS: it used to exit 0 here, which let a
#      force-push or a shallow checkout turn the gate into a pass.
#
# After a force-push that orphaned the old head, re-run the job from a pull
# request (whose base is always known) or push the base commit first.
set -uo pipefail

repo="${1:?usage: resolve-swizzle-base.sh GHOST_TOOLS_DIR}"
event="${EVENT:-}"
before="${BEFORE:-}"
zeros=0000000000000000000000000000000000000000

fail() {
  echo "::error::swizzle gate: $1" >&2
  exit 1
}

reachable() {
  [ -n "$1" ] && [ "$1" != "$zeros" ] && git -C "$repo" cat-file -e "$1^{commit}" 2>/dev/null
}

case "$event" in
  pull_request)
    # The checkout is the merge commit under test; its first parent is exactly
    # the base it was built on.
    base="$(git -C "$repo" rev-parse --verify -q 'HEAD^1^{commit}')" \
      || fail "pull_request event but the checkout has no first parent, so there is no base to compare against"
    ;;
  push)
    if reachable "$before"; then
      base="$(git -C "$repo" rev-parse "$before^{commit}")"
    elif ! git -C "$repo" rev-parse -q --verify 'HEAD^1' >/dev/null; then
      # HEAD has no parent: the root commit.
      echo "::warning::swizzle gate: SKIPPED on purpose: this is the first commit of the repository ($(git -C "$repo" rev-parse --short HEAD)), so there is no earlier revision to compare against. Every later push and pull request is gated and fails if its base cannot be found." >&2
      exit 3
    else
      fail "push event with base '${before:-none}', which is not a reachable commit in a repository that has history. The gate cannot tell whether this change made ghost_buster worse, so it fails instead of passing. Re-run it from a pull request."
    fi
    ;;
  *)
    fail "event '${event:-none}' has no defined base revision (expected pull_request or push)"
    ;;
esac

printf '%s\n' "$base"
