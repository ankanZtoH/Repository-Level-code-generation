def find_max(arr):
    max_val = None
    for i in range(len(arr)):
        if max_val is None or arr[i] > max_val:
            max_val = arr[i]
    return max_val

if __name__ == '__main__':
    arr = [1, 2, 3, 4, 5]
    print(find_max(arr))