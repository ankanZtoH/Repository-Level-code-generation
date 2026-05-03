let counter = 0;

document.getElementById("increment").addEventListener("click", () => {
    counter++;
    document.getElementById("counter").innerHTML = counter;
});

document.getElementById("decrement").addEventListener("click", () => {
    counter--;
    document.getElementById("counter").innerHTML = counter;
});