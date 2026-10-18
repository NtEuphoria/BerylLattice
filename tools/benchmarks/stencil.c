/* Bounded direct stencil baseline. Compile with clang -O3 -std=c11. */
#include <stdio.h>
int main(void) {
    int h, w, a[256];
    if (scanf("%d%d", &h, &w) != 2 || h < 1 || h > 255 || w < 1 || w > 255 || (h+1)*(w+1) > 256) return 1;
    for (int i=0; i<(h+1)*(w+1); i++)
        if (scanf("%d", &a[i]) != 1 || a[i] < 0 || a[i] > 1023) return 1;
    putchar('[');
    for (int r=0; r<h; r++) for (int c=0; c<w; c++) {
        int i=r*(w+1)+c, x=a[i]+1, y=a[i+1]+1, z=a[i+w+1]+1, t=a[i+w+2]+1;
        if (r || c) putchar(',');
        printf("%d", ((x*x+y*y)+z*z)+t*t);
    }
    puts("]");
    return 0;
}
