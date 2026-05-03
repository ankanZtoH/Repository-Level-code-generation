import os

class Storage:
    def __init__(self):
        self.file_name = 'tasks.json'

    def load(self):
        if os.path.exists(self.file_name):
            with open(self.file_name) as f:
                return json.load(f)
        else:
            return []

    def save(self, data):
        with open(self.file_name, 'w') as f:
            json.dump(data, f)
