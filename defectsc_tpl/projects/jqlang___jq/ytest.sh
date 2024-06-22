#!/bin/sh -x

. "${0%/*}/setup" "$@"

msys=false
mingw=false
case "$(uname -s)" in
MSYS*)  msys=true;;
MINGW*) mingw=true;;
esac

JQ_NO_B=$JQ
JQ="$JQ -b"



# CVE-2023-50268: No stack overflow comparing a nan with a large payload
$VALGRIND $Q $JQ '1 != .' <<\EOF >/dev/null
Nan4000
EOF




exit 0 