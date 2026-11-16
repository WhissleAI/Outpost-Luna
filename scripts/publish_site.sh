#!/usr/bin/env bash
# Publish site/ to the gh-pages branch, which GitHub Pages serves at https://whissleai.github.io/Outpost-Luna/.
#
#   bash scripts/publish_site.sh            # copy site/ from the current checkout, commit, push
#   DRY_RUN=1 bash scripts/publish_site.sh  # build the commit locally, do not push
#
# gh-pages is an orphan branch that holds only the site's files (plus .nojekyll, so Pages serves them as they are).
# The script works in a temporary git worktree, so your checkout and its branch are never touched.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SITE="$ROOT/site"
BRANCH="${BRANCH:-gh-pages}"
REMOTE="${REMOTE:-origin}"
[ -f "$SITE/index.html" ] || { echo "no $SITE/index.html" >&2; exit 1; }
python3 "$ROOT/scripts/check_site.py" || { echo "fix the site checks above before publishing" >&2; exit 1; }

SRC_REV="$(git -C "$ROOT" rev-parse --short HEAD)"
TMP="$(mktemp -d)"
cleanup() {
  git -C "$ROOT" worktree remove --force "$TMP" >/dev/null 2>&1 || rm -rf "$TMP"
  git -C "$ROOT" branch -D "pages-tmp-$$" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git -C "$ROOT" fetch -q "$REMOTE" "$BRANCH" 2>/dev/null || true
if git -C "$ROOT" rev-parse -q --verify "refs/remotes/$REMOTE/$BRANCH" >/dev/null; then
  git -C "$ROOT" worktree add -q --detach "$TMP" "$REMOTE/$BRANCH"
else
  git -C "$ROOT" worktree add -q --detach "$TMP"
  git -C "$TMP" checkout -q --orphan "pages-tmp-$$"
fi

# Replace everything with the current site/.
git -C "$TMP" rm -rqf --ignore-unmatch . >/dev/null
find "$TMP" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$SITE"/. "$TMP"/
touch "$TMP/.nojekyll"
git -C "$TMP" add -A

if git -C "$TMP" diff --cached --quiet && git -C "$TMP" rev-parse -q --verify HEAD >/dev/null; then
  echo "gh-pages already matches site/ at $SRC_REV; nothing to publish"
  exit 0
fi
git -C "$TMP" commit -q -m "Publish site/ from $SRC_REV"
echo "built $(git -C "$TMP" rev-parse --short HEAD): site/ from $SRC_REV"

if [ "${DRY_RUN:-0}" = 1 ]; then
  echo "DRY_RUN=1: not pushing"
  exit 0
fi
git -C "$TMP" push -q "$REMOTE" "HEAD:refs/heads/$BRANCH"
echo "pushed to $REMOTE/$BRANCH"
