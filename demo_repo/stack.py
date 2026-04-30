class Stack:
	def __init__(self):
		self.items = []

	def isEmpty(self):
		return len(self.items) == 0

	def push(self, item):
		self.items.append(item)

	def pop(self):
		if self.isEmpty():
			return None
		else:
			return self.items.pop()

	def peek(self):
		if self.isEmpty():
			return None
		else:
			return self.items[-1]

if __name__ == "__main__":
	stack = Stack()
	print(stack.peek())
	stack.push(5)
	print(stack.peek())
	stack.push("hello")
	print(stack.peek())
	stack.pop()
	print(stack.peek())
