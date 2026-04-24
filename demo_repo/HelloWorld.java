public class HelloWorld {
    // Simple Java greeting program
    public static String greet(String name) {
        return "Hello, " + name + "!";
    }

    public static int factorial(int n) {
        if (n < 0) throw new IllegalArgumentException("Negative input");
        if (n <= 1) return 1;
        return n * factorial(n - 1);
    }

    public static void main(String[] args) {
        System.out.println(greet("World"));
        System.out.println("5! = " + factorial(5));
        System.out.println("10! = " + factorial(10));
    }
}
