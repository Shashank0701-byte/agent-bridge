#!/usr/bin/env bash
# Repository guard rails: the cheap, decisive checks.
#
# Everything here maps to something that has actually gone wrong in this repo
# or would break a fresh clone, so a failure is never advisory. Runs in a few
# seconds with nothing but git and grep, which is why it is the one job worth
# keeping on the critical path.
set -uo pipefail

FAILED=0

fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILED=1; }
pass() { printf '  \033[32mok\033[0m    %s\n' "$*"; }
head_() { printf '\n==> %s\n' "$*"; }

# ---------------------------------------------------------------- credentials
head_ "Credentials are not committed"

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  fail ".env is tracked by git -- it holds a live bot token. Untrack it: git rm --cached .env"
else
  pass ".env is not tracked"
fi

# The value in .env.example must stay a placeholder. A real token pasted here
# is the most likely way this repo ever leaks one.
if [ -f .env.example ]; then
  bad=0
  while IFS= read -r line; do
    value="${line#*=}"
    case "$value" in
      ""|*your*|*YOUR*|*xxx*|*XXX*|*example*|*placeholder*) ;;
      *) fail ".env.example looks like it has a real value: ${line%%=*}=..."; bad=1 ;;
    esac
  done < <(grep -E '^[A-Z_]+=' .env.example | grep -vE '^AGENT_BRIDGE_STATE=')
  [ "$bad" -eq 0 ] && pass ".env.example holds placeholders only"
fi

# Scan every blob in the history that was fetched, not just the working tree:
# a token that was committed and then deleted is still a leaked token.
# guard.sh itself is excluded -- it necessarily contains these patterns.
head_ "No secrets anywhere in history"
SECRET_RE='glpat-[A-Za-z0-9_-]{20}|sk-ant-[A-Za-z0-9_-]{24}|gh[pousr]_[A-Za-z0-9]{36}|[MNO][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}'
hits=0
while read -r sha path; do
  case "$path" in ci/guard.sh) continue ;; esac
  if git cat-file blob "$sha" 2>/dev/null | grep -qE "$SECRET_RE"; then
    fail "possible credential in $path (blob $sha)"
    hits=$((hits + 1))
  fi
done < <(git rev-list --objects --all | awk 'NF==2')
[ "$hits" -eq 0 ] && pass "scanned $(git rev-list --objects --all | awk 'NF==2' | wc -l) blobs, nothing token-shaped"

# --------------------------------------------------------------- line endings
# A single \r in .env smuggles a carriage return into the bot token and Discord
# answers 401, which sends you hunting for a permissions problem that does not
# exist. .gitattributes prevents this, but only for people whose git honours it.
head_ "No CRLF in files that run under Linux"
crlf=0
for f in $(git ls-files '*.sh' '*.py' '.env*'); do
  if git show ":$f" | grep -qU $'\r'; then
    fail "$f contains CR -- it will fail with 'bad interpreter: ...^M'"
    crlf=$((crlf + 1))
  fi
done
[ "$crlf" -eq 0 ] && pass "all shell, python and env files are LF"

# ------------------------------------------------------------------ exec bits
# README's very first command is ./scripts/bootstrap.sh. If the file is
# committed 644, a fresh clone answers "Permission denied" and the project is
# broken before anyone reaches the interesting parts.
head_ "Scripts a clone will execute are executable"
modes=0
while read -r mode _ _ path; do
  case "$path" in *.sh) ;; *) continue ;; esac
  git show ":$path" | head -1 | grep -q '^#!' || continue   # sourced libs are exempt
  if [ "$mode" != "100755" ]; then
    fail "$path has a shebang but is committed $mode -- git update-index --chmod=+x '$path'"
    modes=$((modes + 1))
  fi
done < <(git ls-files -s)
[ "$modes" -eq 0 ] && pass "every executable script is committed 755"

printf '\n'
if [ "$FAILED" -ne 0 ]; then
  echo "guard: failed"
  exit 1
fi
echo "guard: all checks passed"
