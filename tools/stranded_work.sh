#!/usr/bin/env bash
#
# Find work that exists on this disk and nowhere else.
#
# Every repository here is a clone of something on GitHub, which makes it easy
# to assume the remote has everything. It does not. A one-off audit on
# 2026-09-07 found 18 commits across four repos that existed on no remote ref
# at all -- including the only copy of a completed adversarial security
# campaign, unreplicated for twelve days. Nothing reported that. Nothing would
# have, until the disk was gone or a clone was deleted to reclaim space.
#
# So this runs on a timer and says nothing unless there is something to say.
#
# Three checks, in descending order of how bad it is to be wrong about them:
#
#   NO REMOTE       a repo with no origin. Everything in it is a single copy.
#   STRANDED        commits reachable from no remote branch AND no remote tag.
#   CANNOT PUSH     the repo is archived on GitHub, so the stranded commits
#                   above cannot be pushed even by someone who notices them.
#                   Checked only where something is actually stranded, since
#                   that is the only case where it matters and it costs a
#                   network call.
#
#
# refs/claude/* is excluded. Those are Claude Code's own rate-limit checkpoints
# -- tool-internal WIP, recreated constantly, and never work anyone needs
# pushed. They were the only thing this reported on its first real run, and a
# report whose only content is noise is a report people stop reading.
#
# The --tags part is load-bearing. `git rev-list --not --remotes` compares
# against remote BRANCHES only, so every commit hanging off a pushed tag looks
# stranded. That false-positived on three repos during the original audit and
# would have made this report noise anyone learns to ignore.

set -uo pipefail

ROOT="${STRANDED_ROOT:-$HOME}"
REPORT="${STRANDED_REPORT:-$HOME/.stranded-work-report.txt}"
found=0
lines=()

emit () { lines+=("$1"); }

for dir in "$ROOT"/*/; do
    repo="$(basename "$dir")"
    [ -d "$dir/.git" ] || continue
    cd "$dir" 2>/dev/null || continue

    if ! git remote get-url origin >/dev/null 2>&1; then
        emit "NO REMOTE    $repo -- nothing in this repo is backed up anywhere"
        found=1
        continue
    fi

    # Quiet: a fetch failure must not turn this into a false alarm, and must
    # not stop the sweep either. Stale remote refs make the count too HIGH,
    # never too low, so the check stays fail-safe if the network is down.
    git fetch --quiet origin >/dev/null 2>&1

    stranded=$(git rev-list --count --exclude='refs/claude/*' --all \
                   --not --remotes --tags 2>/dev/null)
    [ -z "$stranded" ] && stranded=0
    [ "$stranded" = "0" ] && continue

    found=1
    emit "STRANDED     $repo -- $stranded commit(s) on no remote branch or tag"

    # Show what they are; "some commits" is not actionable.
    while IFS= read -r line; do
        [ -n "$line" ] && emit "                 $line"
    done < <(git log --oneline --no-decorate --exclude='refs/claude/*' --all \
                 --not --remotes --tags 2>/dev/null | head -5)

    if command -v gh >/dev/null 2>&1; then
        archived=$(gh repo view --json isArchived -q .isArchived 2>/dev/null)
        if [ "$archived" = "true" ]; then
            emit "  CANNOT PUSH    $repo is ARCHIVED on GitHub and is read-only."
            emit "                 Unarchive, push, re-archive -- or the work stays here."
        fi
    fi
done

if [ "$found" = "0" ]; then
    rm -f "$REPORT" 2>/dev/null
    exit 0
fi

{
    echo "STRANDED WORK  $(date -Iseconds)"
    echo "Commits below exist on this disk and on no remote. Push them, or accept"
    echo "that a disk failure or a deleted clone loses them."
    echo
    printf '%s\n' "${lines[@]}"
} > "$REPORT"

cat "$REPORT"
exit 1
