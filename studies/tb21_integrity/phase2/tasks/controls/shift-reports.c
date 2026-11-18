#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char id[16], meter[16];
    int day, bucket;
    long long delta;
} Event;

static int utc_day(int minute) {
    return minute >= 0 ? minute / 1440 : (minute - 1439) / 1440;
}

static int by_bucket(const void *left, const void *right) {
    const Event *a = left;
    const Event *b = right;
    int meter = strcmp(a->meter, b->meter);
    if (meter != 0) return meter;
    if (a->day != b->day) return a->day - b->day;
    return a->bucket - b->bucket;
}

int main(void) {
    Event events[700];
    Event input;
    int count = 0, day, hour, minute, offset;

    while (scanf("%15s %15s %d %d:%d %d %lld", input.id, input.meter, &day,
                 &hour, &minute, &offset, &input.delta) == 7) {
        int utc = day * 1440 + hour * 60 + minute - offset;
        input.day = utc_day(utc);
        input.bucket = (utc - input.day * 1440) / 30;
        int index = 0;
        while (index < count && strcmp(input.id, events[index].id) != 0) ++index;
        if (index == count) ++count;
        events[index] = input;
    }

    qsort(events, (size_t)count, sizeof events[0], by_bucket);
    for (int begin = 0; begin < count;) {
        long long sum = events[begin].delta;
        int end = begin + 1;
        while (end < count && by_bucket(&events[begin], &events[end]) == 0) {
            sum += events[end++].delta;
        }
        printf("%s %d %d %d %lld\n", events[begin].meter, events[begin].day,
               events[begin].bucket, end - begin, sum);
        begin = end;
    }
    return 0;
}
