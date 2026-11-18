#include <stdio.h>

int main(void) {
    int minimum, maximum, value, count = 1;
    if (scanf("%d", &value) != 1) {
        return 1;
    }
    minimum = maximum = value;
    long long total = value;
    while (scanf("%d", &value) == 1) {
        count++;
        total += value;
        if (value < minimum) minimum = value;
        if (value > maximum) maximum = value;
    }
    printf("%d %d %d %lld\n", count, minimum, maximum, total);
    return 0;
}
