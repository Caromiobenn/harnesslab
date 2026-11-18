#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char key[13], label[61];
    long long quantity;
} Item;

static int by_key(const void *left, const void *right) {
    const Item *a = left;
    const Item *b = right;
    return strcmp(a->key, b->key);
}

static const char *read_label(const char *input, char *label) {
    if (*input == '"') {
        ++input;
        while (*input != '\0') {
            if (*input == '"') {
                ++input;
                if (*input != '"') break;
            }
            *label++ = *input++;
        }
    } else {
        while (*input != ',' && *input != '\0') *label++ = *input++;
    }
    *label = '\0';
    return input + 1;
}

static void print_label(const char *label) {
    if (!strpbrk(label, ",\"")) {
        fputs(label, stdout);
        return;
    }
    putchar('"');
    for (; *label != '\0'; ++label) {
        if (*label == '"') putchar('"');
        putchar(*label);
    }
    putchar('"');
}

int main(void) {
    Item items[800];
    int count = 0;
    char line[160];
    while (fgets(line, sizeof line, stdin)) {
        char *comma = strchr(line, ',');
        if (!comma) continue;
        *comma = '\0';
        char label[61];
        const char *quantity = read_label(comma + 1, label);
        int index = 0;
        while (index < count && strcmp(line, items[index].key) != 0) ++index;
        if (index == count) {
            items[index] = (Item){0};
            strcpy(items[index].key, line);
            ++count;
        }
        if (label[0] != '\0') strcpy(items[index].label, label);
        items[index].quantity += strtoll(quantity, NULL, 10);
    }
    qsort(items, (size_t)count, sizeof items[0], by_key);
    for (int i = 0; i < count; ++i) {
        printf("%s,", items[i].key);
        print_label(items[i].label);
        printf(",%lld\n", items[i].quantity);
    }
    return 0;
}
