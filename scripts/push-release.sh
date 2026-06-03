#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)

remote="origin"
branch=""
version_override=""
assume_yes=0
skip_tests=0

usage() {
  cat <<'EOF'
Usage: scripts/push-release.sh [options]

Validate release metadata, push the release branch, create an annotated tag,
and push that tag so GitHub Actions builds a draft release.

Options:
  --version VERSION   Require lyon.__version__ to match VERSION.
  --branch BRANCH     Require and push BRANCH. Defaults to release/VERSION.
  --remote REMOTE     Git remote to push. Defaults to the branch upstream remote.
  --skip-tests        Skip the focused local release-script test gate.
  --yes               Do not prompt before pushing the branch and tag.
  -h, --help          Show this help.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      [ "$#" -ge 2 ] || die "--version requires a value."
      version_override="$2"
      shift 2
      ;;
    --branch)
      [ "$#" -ge 2 ] || die "--branch requires a value."
      branch="$2"
      shift 2
      ;;
    --remote)
      [ "$#" -ge 2 ] || die "--remote requires a value."
      remote="$2"
      shift 2
      ;;
    --skip-tests)
      skip_tests=1
      shift
      ;;
    --yes)
      assume_yes=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

cd "$repo_root"

if [ ! -d .git ]; then
  die "run this script from inside the Sea Lyon Media Manager git checkout."
fi

find_python() {
  if [ -x ".venv/bin/python" ]; then
    printf '%s\n' ".venv/bin/python"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi
  die "could not find Python. Create .venv or install python3."
}

python_bin=$(find_python)

app_version=$("$python_bin" - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

tree = ast.parse(Path("lyon/__init__.py").read_text(encoding="utf-8"))
for node in tree.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__version__":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    print(node.value.value)
                    raise SystemExit
raise SystemExit("lyon.__version__ was not found")
PY
)

if [ -n "$version_override" ] && [ "$version_override" != "$app_version" ]; then
  die "lyon.__version__ is $app_version, not requested version $version_override."
fi

version="$app_version"
case "$version" in
  [0-9]*.[0-9]*.[0-9]*)
    ;;
  *)
    die "version $version does not look like a release version."
    ;;
esac

tag="v$version"
expected_branch="release/$version"
if [ -z "$branch" ]; then
  branch="$expected_branch"
fi

current_branch=$(git branch --show-current)
if [ "$current_branch" != "$branch" ]; then
  die "current branch is $current_branch; expected $branch."
fi

upstream_ref=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
if [ -z "$upstream_ref" ]; then
  die "branch $branch has no upstream. Set upstream before releasing."
fi

upstream_remote=${upstream_ref%%/*}
if [ "$remote" = "origin" ]; then
  remote="$upstream_remote"
fi
if [ "$upstream_ref" != "$remote/$branch" ]; then
  die "branch upstream is $upstream_ref, expected $remote/$branch."
fi

require_clean_worktree() {
  label="$1"
  if [ -n "$(git status --short)" ]; then
    git status --short >&2
    die "working tree is not clean $label."
  fi
}

require_tag_workflow() {
  file="$1"
  grep -q 'tags:' "$file" || die "$file has no tag trigger."
  grep -q "v\\*\\.\\*\\.\\*" "$file" || die "$file does not trigger on v*.*.* tags."
}

require_clean_worktree "before release"

require_tag_workflow ".github/workflows/windows-build.yml"
require_tag_workflow ".github/workflows/macos-build.yml"
grep -q 'types:' ".github/workflows/publish-appcast.yml" || die "publish-appcast workflow is missing release type trigger."

"$python_bin" scripts/changelog-section.py "$version" >/dev/null

git fetch "$remote" "$branch" --tags

remote_ref="$remote/$branch"
if ! git rev-parse --verify "$remote_ref" >/dev/null 2>&1; then
  die "remote branch $remote_ref was not found."
fi

read -r ahead behind < <(git rev-list --left-right --count "HEAD...$remote_ref")
if [ "$behind" != "0" ]; then
  die "$branch is behind $remote_ref by $behind commit(s). Pull before releasing."
fi

head_sha=$(git rev-parse HEAD)
local_tag_exists=0
if git show-ref --verify --quiet "refs/tags/$tag"; then
  local_tag_exists=1
  tag_target=$(git rev-parse "$tag^{commit}")
  if [ "$tag_target" != "$head_sha" ]; then
    die "local tag $tag points to $tag_target, not HEAD $head_sha."
  fi
fi

if git ls-remote --exit-code --tags "$remote" "$tag" >/dev/null 2>&1; then
  die "remote tag $tag already exists on $remote."
fi

if [ "$skip_tests" -eq 0 ]; then
  "$python_bin" -m pytest -q \
    tests/test_release_workflows.py \
    tests/test_packaging.py \
    tests/test_push_release_script.py
fi

require_clean_worktree "after local tests"

cat <<EOF
Ready to start the draft release:
  version: $version
  branch:  $branch
  tag:     $tag
  head:    $head_sha
  remote:  $remote
EOF

if [ "$assume_yes" -ne 1 ]; then
  printf 'Type %s to push the branch and tag: ' "$tag"
  read -r answer
  [ "$answer" = "$tag" ] || die "aborted."
fi

git push "$remote" "$branch"

if [ "$local_tag_exists" -eq 0 ]; then
  git tag -a "$tag" -m "Sea Lyon Media Manager $version"
else
  printf 'Reusing existing local tag %s at HEAD.\n' "$tag"
fi

git push "$remote" "$tag"

cat <<EOF
Draft release started for $tag.

Next steps:
  1. Watch the Windows build and macOS build workflows for $tag.
  2. Smoke-test the assets attached to the draft GitHub Release.
  3. Make the GitHub Release public manually when ready; that triggers
     publish-appcast.yml to deploy appcast.xml to GitHub Pages.
EOF
