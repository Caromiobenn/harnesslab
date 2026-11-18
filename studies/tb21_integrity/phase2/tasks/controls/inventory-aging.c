#include <stdio.h>

typedef struct {
    char kind;
    int day, lifetime, quantity, filled;
} Record;

typedef struct {
    int expires, remaining;
} Lot;

int main(void) {
    Record records[700];
    Lot lots[700];
    int count = 0, lot_count = 0, last_day = -1;
    char kind;
    int day, units, lifetime;
    while (scanf(" %c%d", &kind, &day) == 2) {
        lifetime = 0;
        if (kind == 'R' && scanf("%d", &lifetime) != 1) return 1;
        if (scanf("%d", &units) != 1) return 1;
        records[count++] = (Record){kind, day, lifetime, units, 0};
        if (day > last_day) last_day = day;
    }
    for (int active = 0; active <= last_day; ++active) {
        for (int i = 0; i < lot_count; ++i) {
            if (lots[i].expires <= active) lots[i].remaining = 0;
        }
        for (int i = 0; i < count; ++i) {
            Record r = records[i];
            if (r.kind == 'R' && r.day == active) {
                lots[lot_count++] = (Lot){active + r.lifetime, r.quantity};
            }
        }
        for (int i = 0; i < count; ++i) {
            Record *r = &records[i];
            if (r->kind != 'D' || r->day != active) continue;
            int need = r->quantity;
            for (int k = 0; k < lot_count && need > 0; ++k) {
                int used = lots[k].remaining < need ? lots[k].remaining : need;
                lots[k].remaining -= used;
                need -= used;
            }
            r->filled = r->quantity - need;
        }
    }
    for (int i = 0; i < count; ++i) {
        if (records[i].kind == 'D') printf("%d\n", records[i].filled);
    }
    int remaining = 0;
    for (int i = 0; i < lot_count; ++i) remaining += lots[i].remaining;
    printf("%d\n", remaining);
    return 0;
}
