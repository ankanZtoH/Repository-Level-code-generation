import json
import os

class Tasks:
    def __init__(self):
        self.tasks = []
        self.load_tasks()

    def run(self, args):
        if len(args) == 0:
            print('Usage: python main.py <command> [<arguments>]')
            return

        command = args[0]
        arguments = args[1:]

        if command == 'add':
            self.add_task(arguments)
        elif command == 'delete':
            self.delete_task(arguments)
        elif command == 'list':
            self.list_tasks()
        else:
            print('Invalid command')

    def add_task(self, arguments):
        if len(arguments) < 2:
            print('Usage: python main.py add <task> [<priority>]')
            return

        task = arguments[0]
        priority = int(arguments[1]) if len(arguments) > 1 else 5
        self.tasks.append({'task': task, 'priority': priority})
        self.save_tasks()

    def delete_task(self, arguments):
        if len(arguments) != 1:
            print('Usage: python main.py delete <index>')
            return

        index = int(arguments[0])
        del self.tasks[index]
        self.save_tasks()

    def list_tasks(self):
        for task in self.tasks:
            print('Task:', task['task'], 'Priority:', task['priority'])

    def load_tasks(self):
        if os.path.exists('tasks.json'):
            with open('tasks.json') as f:
                self.tasks = json.load(f)

    def save_tasks(self):
        with open('tasks.json', 'w') as f:
            json.dump(self.tasks, f)
