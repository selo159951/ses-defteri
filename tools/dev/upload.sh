#!/bin/bash
# usage: upload.sh <tag> <file>...  (replaces same-named assets on that release of selo159951/ses-defteri; curl, because gh times out on big files)
GH="/c/Program Files/GitHub CLI/gh.exe"; command -v gh >/dev/null && GH=gh
REPO=selo159951/ses-defteri
TAG=$1; shift
RID=$("$GH" api repos/$REPO/releases --jq ".[] | select(.tag_name==\"$TAG\") | .id")
TOKEN=$("$GH" auth token)
for f in "$@"; do
  name=$(basename "$f")
  for i in 1 2 3 4 5; do
    old=$("$GH" api repos/$REPO/releases/$RID/assets --paginate --jq ".[] | select(.name==\"$name\") | .id")
    [ -n "$old" ] && "$GH" api -X DELETE repos/$REPO/releases/assets/$old >/dev/null
    code=$(curl --http1.1 -sS -o /dev/null -w "%{http_code}" --retry 0 --speed-time 120 --speed-limit 1024 \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/octet-stream" \
      -X POST -T "$f" "https://uploads.github.com/repos/$REPO/releases/$RID/assets?name=$name")
    if [ "$code" = "201" ]; then echo "OK $name"; break; fi
    echo "try $i $name -> $code"; sleep 15
  done
done
"$GH" release view $TAG -R $REPO --json assets -q '.assets[]|.name+" "+(.size|tostring)+" "+.state'
