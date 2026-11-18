#include <stdio.h>
#include <stdlib.h>

struct interval {
    int start, end;
};

static int compare_starts(const void *left, const void *right) {
    const struct interval *a = left;
    const struct interval *b = right;
    return a->start - b->start;
}

int main(void) {
    struct interval intervals[1000];
    int start, end, count = 0;
    while (scanf("%d%d", &start, &end) == 2) {
        if (start < end) {
            intervals[count++] = (struct interval){start, end};
        }
    }
    qsort(intervals, count, sizeof(intervals[0]), compare_starts);
    int length = 0, components = 0;
    if (count > 0) {
        start = intervals[0].start;
        end = intervals[0].end;
        components = 1;
        for (int i = 1; i < count; i++) {
            if (intervals[i].start > end) {
                length += end - start;
                components++;
                start = intervals[i].start;
                end = intervals[i].end;
            } else if (intervals[i].end > end) {
                end = intervals[i].end;
            }
        }
        length += end - start;
    }
    printf("%d %d\n", length, components);
    return 0;
}
