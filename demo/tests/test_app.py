import unittest
from main import Tasks

class TestApp(unittest.TestCase):
    def test_add_task(self):
        task = Tasks()
        task.run(['add', 'test task']) # add a new task with priority 5
        self.assertEqual(len(task.tasks), 1)
        self.assertEqual(task.tasks[0]['task'], 'test task')
        self.assertEqual(task.tasks[0]['priority'], 5)

    def test_delete_task(self):
        task = Tasks()
        task.run(['add', 'test task']) # add a new task with priority 5
        task.run(['delete', '0']) # delete the first task
        self.assertEqual(len(task.tasks), 0)

    def test_list_tasks(self):
        task = Tasks()
        task.run(['add', 'test task 1']) # add a new task with priority 5
        task.run(['add', 'test task 2']) # add another new task with priority 3
        task.run(['list']) # list all tasks
        self.assertEqual(len(task.tasks), 2)
        self.assertEqual(task.tasks[0]['task'], 'test task 1')
        self.assertEqual(task.tasks[0]['priority'], 5)
        self.assertEqual(task.tasks[1]['task'], 'test task 2')
        self.assertEqual(task.tasks[1]['priority'], 3)
