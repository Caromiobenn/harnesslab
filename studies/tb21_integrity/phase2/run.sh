#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo 'Usage: sh phase2/run.sh calibration|matrix ENV_FILE OUTPUT_DIRECTORY' >&2
    exit 2
fi

study=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
profile=$1
environment=$2
output=$3
case "$profile" in
    calibration)
        set -- --toolchain ready --repeats 1 --no-review --workers 4 \
            --order-seed 18017 --score-seed 18017
        ;;
    matrix)
        set -- --repeats 3 --review --workers 6 --order-seed 18053 --score-seed 18053
        ;;
    *)
        echo "Unknown profile: $profile" >&2
        exit 2
        ;;
esac

exec python3 "$study/run_study.py" --suite phase2 --env-file "$environment" \
    --out "$output" --trace --max-tokens 4096 --max-responses 20 \
    --review-max-responses 4 --timeout 210 "$@"
