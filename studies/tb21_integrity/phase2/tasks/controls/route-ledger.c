#include <limits.h>
#include <stdio.h>

#define MOD 1000000007

typedef struct {
    int from, to, toll;
} Edge;

static void solve(int n, const Edge *edges, int count, int start, int end) {
    int cost[51], legs[51], paths[51] = {0};
    for (int i = 1; i <= n; ++i) {
        cost[i] = INT_MAX;
        legs[i] = n + 1;
    }
    cost[start] = legs[start] = 0;
    for (int round = 0; round < n - 1; ++round) {
        int changed = 0;
        for (int i = 0; i < count; ++i) {
            Edge e = edges[i];
            if (cost[e.from] == INT_MAX) continue;
            int candidate = cost[e.from] + e.toll;
            if (candidate < cost[e.to] ||
                (candidate == cost[e.to] && legs[e.from] + 1 < legs[e.to])) {
                cost[e.to] = candidate;
                legs[e.to] = legs[e.from] + 1;
                changed = 1;
            }
        }
        if (!changed) break;
    }
    if (cost[end] == INT_MAX) {
        puts("-1 0 0");
        return;
    }
    paths[start] = 1;
    for (int depth = 0; depth < legs[end]; ++depth) {
        for (int i = 0; i < count; ++i) {
            Edge e = edges[i];
            if (legs[e.from] == depth && legs[e.to] == depth + 1 &&
                cost[e.to] == cost[e.from] + e.toll) {
                paths[e.to] = (paths[e.to] + paths[e.from]) % MOD;
            }
        }
    }
    printf("%d %d %d\n", cost[end], legs[end], paths[end]);
}

int main(void) {
    int n, m, q;
    if (scanf("%d%d%d", &n, &m, &q) != 3) return 1;
    Edge edges[500];
    for (int i = 0; i < m; ++i) {
        if (scanf("%d%d%d", &edges[i].from, &edges[i].to, &edges[i].toll) != 3) return 1;
    }
    for (int i = 0; i < q; ++i) {
        int start, end;
        if (scanf("%d%d", &start, &end) != 2) return 1;
        solve(n, edges, m, start, end);
    }
    return 0;
}
