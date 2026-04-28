class Node:
	def __init__(self, data):
		self.data = data
		self.next = None

class LinkedList:
	def __init__(self):
		self.head = None

	def append(self, data):
		new_node = Node(data)
		if self.head is None:
			self.head = new_node
		else:
			current = self.head
			while current.next is not None:
				current = current.next
			current.next = new_node

if __name__ == "__main__":
	my_list = LinkedList()
	my_list.append(1)
	my_list.append(2)
	my_list.append(3)
	print(my_list.head.data)
	print(my_list.head.next.data)
	print(my_list.head.next.next.data)