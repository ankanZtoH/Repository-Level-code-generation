import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from processor import get_total_price
from formatter import format_receipt

def run_app():
    price = 10
    qty = 5
    total = get_total_price(price, qty)
    receipt = format_receipt(total)
    print(receipt)

if __name__ == "__main__":
    print("Running buggy app...")
    run_app()