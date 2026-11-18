#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct event_total {
    char name[13];
    long long total;
};

static int compare_names(const void *left, const void *right) {
    const struct event_total *a = left;
    const struct event_total *b = right;
    return strcmp(a->name, b->name);
}

int main(void) {
    struct event_total totals[1000] = {0};
    char name[13];
    int delta, count = 0;
    while (scanf("%12s%d", name, &delta) == 2) {
        int index = 0;
        while (index < count && strcmp(totals[index].name, name) != 0) {
            index++;
        }
        if (index == count) {
            strcpy(totals[count].name, name);
            count++;
        }
        totals[index].total += delta;
    }
    qsort(totals, count, sizeof(totals[0]), compare_names);
    for (int i = 0; i < count; i++) {
        printf("%s %lld\n", totals[i].name, totals[i].total);
    }
    return 0;
}
