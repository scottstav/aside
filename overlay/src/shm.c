#include "shm.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

uint32_t *shm_alloc(size_t size, int *out_fd)
{
    int fd = -1;
    char name[32];

    for (int i = 0; i < 256; i++) {
        snprintf(name, sizeof(name), "/aside-overlay-%d", i);
        fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
        if (fd >= 0) {
            shm_unlink(name);
            break;
        }
        if (errno != EEXIST) {
            perror("shm_open");
            return NULL;
        }
    }

    if (fd < 0) {
        fprintf(stderr, "shm_alloc: failed to create shm object\n");
        return NULL;
    }

    if (ftruncate(fd, (off_t)size) < 0) {
        perror("ftruncate");
        close(fd);
        return NULL;
    }

    uint32_t *data = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (data == MAP_FAILED) {
        perror("mmap");
        close(fd);
        return NULL;
    }

    *out_fd = fd;
    return data;
}
