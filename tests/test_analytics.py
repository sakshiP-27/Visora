"""
Test file for /getanalytics endpoint logic.
Run directly: python -m tests.test_analytics
This computes analytics from receipt data without any API or DB dependency.
"""

import json

# Sample payload that backend would send (from DB)
sample_request = {
    "userID": "user123",
    "currency": "INR",
    "period": "monthly",
    "receipts": [
        {
            "merchant": "Reliance Smart",
            "date": "2026-03-01",
            "totalAmount": 845.50,
            "items": [
                {"name": "Milk", "price": 60, "quantity": 1, "category": "Food & Groceries"},
                {"name": "Bread", "price": 45, "quantity": 1, "category": "Food & Groceries"},
                {"name": "Shampoo", "price": 240, "quantity": 2, "category": "Personal Care"},
                {"name": "Detergent", "price": 500.50, "quantity": 1, "category": "Home & Furniture"},
            ],
        },
        {
            "merchant": "Shell Petrol Pump",
            "date": "2026-03-03",
            "totalAmount": 2000,
            "items": [
                {"name": "Petrol", "price": 2000, "quantity": 1, "category": "Fuel"},
            ],
        },
        {
            "merchant": "Zara",
            "date": "2026-03-05",
            "totalAmount": 4500,
            "items": [
                {"name": "T-Shirt", "price": 1500, "quantity": 1, "category": "Clothing & Fashion"},
                {"name": "Jeans", "price": 3000, "quantity": 1, "category": "Clothing & Fashion"},
            ],
        },
        {
            "merchant": "Swiggy",
            "date": "2026-03-05",
            "totalAmount": 650,
            "items": [
                {"name": "Biryani", "price": 350, "quantity": 1, "category": "Dining Out"},
                {"name": "Butter Naan", "price": 150, "quantity": 2, "category": "Dining Out"},
                {"name": "Delivery Fee", "price": 150, "quantity": 1, "category": "Miscellaneous"},
            ],
        },
        {
            "merchant": "DMart",
            "date": "2026-03-10",
            "totalAmount": 1200,
            "items": [
                {"name": "Rice 5kg", "price": 400, "quantity": 1, "category": "Food & Groceries"},
                {"name": "Cooking Oil", "price": 250, "quantity": 1, "category": "Food & Groceries"},
                {"name": "Soap", "price": 150, "quantity": 3, "category": "Personal Care"},
                {"name": "Biscuits", "price": 400, "quantity": 4, "category": "Food & Groceries"},
            ],
        },
    ],
}


def compute_analytics(request: dict) -> dict:
    """
    Pure computation — no LLM needed.
    Takes receipt data and returns analytics response matching
    expense.analytics.response.json schema.
    """
    receipts = request["receipts"]

    # Total spent
    total_spent = sum(r["totalAmount"] for r in receipts)

    # Category breakdown — sum item prices by category across all receipts
    category_totals: dict[str, float] = {}
    for receipt in receipts:
        for item in receipt["items"]:
            category = item["category"]
            category_totals[category] = category_totals.get(category, 0) + item["price"]

    category_breakdown = [
        {"category": cat, "amount": round(amt, 2)}
        for cat, amt in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    ]

    # Daily spending — sum totalAmount per date
    daily_totals: dict[str, float] = {}
    for receipt in receipts:
        date = receipt["date"]
        daily_totals[date] = daily_totals.get(date, 0) + receipt["totalAmount"]

    daily_spending = [
        {"date": date, "amount": round(amt, 2)}
        for date, amt in sorted(daily_totals.items())
    ]

    return {
        "total_spent": round(total_spent, 2),
        "category_breakdown": category_breakdown,
        "daily_spending": daily_spending,
    }


if __name__ == "__main__":
    result = compute_analytics(sample_request)
    print("=== Analytics Response ===")
    print(json.dumps(result, indent=2))

    # Basic validations
    assert result["total_spent"] == 9195.5, f"Expected 9195.5, got {result['total_spent']}"
    assert len(result["category_breakdown"]) > 0, "Category breakdown should not be empty"
    assert len(result["daily_spending"]) > 0, "Daily spending should not be empty"

    # Check category totals add up
    cat_total = sum(c["amount"] for c in result["category_breakdown"])
    item_total = sum(item["price"] for r in sample_request["receipts"] for item in r["items"])
    assert round(cat_total, 2) == round(item_total, 2), f"Category total {cat_total} != item total {item_total}"

    print("\n✅ All analytics validations passed!")
