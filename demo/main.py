def add(a, b):
    return a + b

import sys

from tasks import Tasks

if __name__ == '__main__':
    task = Tasks()
    task.run(sys.argv[1:])

