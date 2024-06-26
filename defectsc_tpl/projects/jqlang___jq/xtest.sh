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



# CVE-2023-50246: No heap overflow for '-10E-1000000001'
$VALGRIND $Q $JQ . <<\NUM
-10E-1000000001
NUM

exit 0 