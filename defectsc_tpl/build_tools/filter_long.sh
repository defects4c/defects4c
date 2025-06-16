#!/usr/bin/env bash
#
# filter_by_name_then_time.sh — first select by name, then by elapsed time,
# and print PID, elapsed (HH:MM:SS), and full command.

THRESHOLD=1800  # seconds (30 min)

ps -eo pid,etimes,etime,args --no-headers \
  | while read -r pid etimes etime args; do
      exe=${args%% *}

      case "$exe" in
        /out/*          \
      | /usr/bin/ld*    \
      | *tcpdump* \
      | /usr/local/bin/clang++* \
      | build_*        \
      | ctest*         \
      | ninja* )
        if [ "$etimes" -gt "$THRESHOLD" ]; then
          # PID | ELAPSED (HH:MM:SS) | CMD
          printf '%6s  %-8s  %s\n' "$pid" "$etime" "$args"
        fi
        ;;
      esac
    done


