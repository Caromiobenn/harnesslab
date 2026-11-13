/* Task-process-only loopback port virtualization; the provider daemon is untouched. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <netinet/in.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

static int ports(unsigned short *from, unsigned short *to) {
    const char *a = getenv("BENCHMARK_LOOPBACK_FROM");
    const char *b = getenv("BENCHMARK_LOOPBACK_TO");
    char *end;
    long x, y;
    if (!a || !b) return 0;
    x = strtol(a, &end, 10);
    if (*end || x < 1 || x > 65535) return 0;
    y = strtol(b, &end, 10);
    if (*end || y < 1 || y > 65535 || x == y) return 0;
    *from = htons((unsigned short)x);
    *to = htons((unsigned short)y);
    return 1;
}

static const struct sockaddr *redirect(const struct sockaddr *address, socklen_t length,
                                       struct sockaddr_storage *copy, int binding) {
    unsigned short from, to;
    if (!address || length > sizeof(*copy) || !ports(&from, &to)) return address;
    if (address->sa_family == AF_INET && length >= sizeof(struct sockaddr_in)) {
        const struct sockaddr_in *v4 = (const struct sockaddr_in *)address;
        unsigned long host = ntohl(v4->sin_addr.s_addr);
        if (v4->sin_port != from || (!binding && host != 0 && (host >> 24) != 127)) return address;
        memcpy(copy, address, length);
        ((struct sockaddr_in *)copy)->sin_port = to;
        return (const struct sockaddr *)copy;
    }
    if (address->sa_family == AF_INET6 && length >= sizeof(struct sockaddr_in6)) {
        const struct sockaddr_in6 *v6 = (const struct sockaddr_in6 *)address;
        int local = IN6_IS_ADDR_LOOPBACK(&v6->sin6_addr) || IN6_IS_ADDR_UNSPECIFIED(&v6->sin6_addr);
        if (IN6_IS_ADDR_V4MAPPED(&v6->sin6_addr)) {
            unsigned long host;
            unsigned int value;
            memcpy(&value, &v6->sin6_addr.s6_addr[12], sizeof(value));
            host = ntohl(value);
            local = host == 0 || (host >> 24) == 127;
        }
        if (v6->sin6_port != from || (!binding && !local)) return address;
        memcpy(copy, address, length);
        ((struct sockaddr_in6 *)copy)->sin6_port = to;
        return (const struct sockaddr *)copy;
    }
    return address;
}

int bind(int fd, const struct sockaddr *address, socklen_t length) {
    int (*original)(int, const struct sockaddr *, socklen_t) = dlsym(RTLD_NEXT, "bind");
    struct sockaddr_storage copy;
    return original(fd, redirect(address, length, &copy, 1), length);
}

int connect(int fd, const struct sockaddr *address, socklen_t length) {
    int (*original)(int, const struct sockaddr *, socklen_t) = dlsym(RTLD_NEXT, "connect");
    struct sockaddr_storage copy;
    return original(fd, redirect(address, length, &copy, 0), length);
}
