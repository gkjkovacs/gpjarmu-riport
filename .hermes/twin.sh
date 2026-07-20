#!/usr/bin/env bash
# twin.sh — A gpjarmu-riport → gpjarmu-riport-v2 tükrözés utolsó lépései.
# Akkor kell, ha a GitHub repot már létrehoztad (akár gh-vel, akár manuálisan a weben),
# és már van hozzáférés a push-hoz. Ez a script csak beállítja a remote-ot és feltolja.
#
# Használat:
#   ./twin.sh                 # a default repo URL-t használja
#   ./twin.sh git@github.com:gkjkovacs/gpjarmu-riport-v2.git
#   ./twin.sh https://github.com/gkjkovacs/gpjarmu-riport-v2.git
#
# Előfeltétel: a munka már commit-olva van a main ágon.

set -euo pipefail

DEFAULT_URL="https://github.com/gkjkovacs/gpjarmu-riport-v2.git"
URL="${1:-$DEFAULT_URL}"

if [ ! -d .git ]; then
  echo "HIBA: ez nem egy git repo. Futtassd a gpjarmu-riport-v2 mappából." >&2
  exit 1
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "→ branch: $CURRENT_BRANCH"
echo "→ remote url: $URL"

if git remote get-url origin >/dev/null 2>&1; then
  echo "→ origin már létezik, felülírom: $(git remote get-url origin) → $URL"
  git remote set-url origin "$URL"
else
  git remote add origin "$URL"
fi

git push -u origin "$CURRENT_BRANCH"
echo "✓ push kész. Repo: $URL"
