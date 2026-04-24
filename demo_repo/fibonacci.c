#include <stdio.h>

// Fibonacci sequence - has an off-by-one bug
int fibonacci(int n) {
    if (n <= 0) return 0;
    if (n == 1) return 1;

    int a = 0, b = 1, temp;
    for (int i = 2; i < n; i++) {  // BUG: should be i <= n
        temp = a + b;
        a = b;
        b = temp;
    }
    return b;
}

int main() {
    printf("Fibonacci sequence:\n");
    for (int i = 0; i <= 10; i++) {
        printf("fib(%d) = %d\n", i, fibonacci(i));
    }
    return 0;
}
