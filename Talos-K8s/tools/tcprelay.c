/* minimal concurrent TCP relay: listen :LISTEN, fork per conn -> connect DST:DPORT, pump both ways */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <poll.h>

#ifndef LISTEN_PORT
#define LISTEN_PORT 8090
#endif
#ifndef DST_IP
#define DST_IP "10.0.0.70"
#endif
#ifndef DST_PORT
#define DST_PORT 8090
#endif

static void pump(int a, int b) {
    char buf[16384];
    struct pollfd p[2] = {{a, POLLIN, 0}, {b, POLLIN, 0}};
    for (;;) {
        if (poll(p, 2, 3600000) <= 0) return;
        if (p[0].revents & POLLIN) {
            ssize_t n = read(a, buf, sizeof buf);
            if (n <= 0) return;
            ssize_t off = 0;
            while (off < n) {
                ssize_t w = write(b, buf + off, n - off);
                if (w <= 0) return;
                off += w;
            }
        }
        if (p[1].revents & POLLIN) {
            ssize_t n = read(b, buf, sizeof buf);
            if (n <= 0) return;
            ssize_t off = 0;
            while (off < n) {
                ssize_t w = write(a, buf + off, n - off);
                if (w <= 0) return;
                off += w;
            }
        }
        if (p[0].revents & (POLLHUP | POLLERR)) return;
        if (p[1].revents & (POLLHUP | POLLERR)) return;
    }
}

static void serve(int c) {
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) { close(c); _exit(1); }
    struct sockaddr_in d = {0};
    d.sin_family = AF_INET;
    d.sin_port = htons(DST_PORT);
    inet_pton(AF_INET, DST_IP, &d.sin_addr);
    int one = 1;
    setsockopt(s, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    if (connect(s, (struct sockaddr *)&d, sizeof d) < 0) { close(c); close(s); _exit(1); }
    setsockopt(c, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    pump(c, s);
    close(c);
    close(s);
    _exit(0);
}

int main(void) {
    signal(SIGCHLD, SIG_IGN);
    signal(SIGPIPE, SIG_IGN);
    int ls = socket(AF_INET, SOCK_STREAM, 0);
    if (ls < 0) { perror("socket"); return 1; }
    int one = 1;
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    struct sockaddr_in la = {0};
    la.sin_family = AF_INET;
    la.sin_addr.s_addr = htonl(INADDR_ANY);
    la.sin_port = htons(LISTEN_PORT);
    if (bind(ls, (struct sockaddr *)&la, sizeof la) < 0) { perror("bind"); return 1; }
    if (listen(ls, 256) < 0) { perror("listen"); return 1; }
    fprintf(stderr, "tcprelay: listening :%d -> %s:%d\n", LISTEN_PORT, DST_IP, DST_PORT);
    for (;;) {
        int c = accept(ls, NULL, NULL);
        if (c < 0) continue;
        pid_t pid = fork();
        if (pid == 0) serve(c);
        close(c);
    }
}
