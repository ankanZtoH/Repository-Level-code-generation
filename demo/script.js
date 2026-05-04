let counter = 0;

document.getElementById('increment').addEventListener('click', () => {
    counter++;
    document.getElementById('counter').textContent = counter;
});

document.getElementById('decrement').addEventListener('click', () => {
    if (counter > 0) {
        counter--;
    }
    document.getElementById('counter').textContent = counter;
});