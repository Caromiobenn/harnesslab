#!/bin/sh
set -eu

driver=$(readlink -f "$(command -v gcc)")
cc1=$(gcc -print-prog-name=cc1)
compiler_support=$(dirname "$cc1")
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

mkdir -p "$stage/bin" "$stage/libexec" /opt/study-toolchain
cp "$driver" "$stage/libexec/gcc"
cp "$cc1" "$stage/libexec/cc1"
cat > "$stage/bin/cc" <<EOF
#!/bin/sh
set -eu
prefix=\$(CDPATH='' cd -- "\$(dirname -- "\$0")/.." && pwd)
exec "\$prefix/libexec/gcc" -B"\$prefix/libexec/" -B"$compiler_support/" "\$@"
EOF
chmod 755 "$stage/bin/cc"
tar -czf /opt/study-toolchain/cc.tar.gz -C "$stage" bin libexec

# Record every alias before removing its target.
for frontend in /usr/bin/*gcc* /usr/bin/cc /bin/cc; do
    if [ "$(readlink -f "$frontend")" = "$driver" ]; then
        printf '%s\n' "$frontend"
    fi
done > "$stage/frontend-aliases"
while IFS= read -r frontend; do
    rm -f -- "$frontend"
done < "$stage/frontend-aliases"
rm -- "$cc1"

cd "$stage"
printf '%s\n' '#include <stdio.h>' 'int main(void) { puts("toolchain-ready"); }' > probe.c
bin/cc -std=c11 probe.c -o probe
test "$(./probe)" = toolchain-ready
! command -v gcc
! command -v cc
