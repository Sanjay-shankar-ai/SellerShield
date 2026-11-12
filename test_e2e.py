import json
import urllib.request
import urllib.parse
import sys

BASE_URL = "http://127.0.0.1:8000"

def request(endpoint, method="GET", data=None, token=None):
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def run_tests():
    print("=== 1. Checking Health Endpoint ===")
    status, res = request("/api/health")
    print(f"Health: status={status}, res={res}")
    assert status == 200, "Health endpoint failed"
    assert res.get("has_api_key") == True, "API key not active"

    print("\n=== 2. Testing Customer Login (rahul@gmail.com) ===")
    status, res = request("/api/auth/login", method="POST", data={
        "email": "rahul@gmail.com",
        "password": "rahul123"
    })
    print(f"Login customer: status={status}, user={res.get('user')}")
    assert status == 200, "Customer login failed"
    customer_token = res["access_token"]
    assert res["user"]["role"] == "CUSTOMER"

    print("\n=== 3. Testing Admin Login (admin@sellershield.com) ===")
    status, res = request("/api/auth/login", method="POST", data={
        "email": "admin@sellershield.com",
        "password": "admin123"
    })
    print(f"Login admin: status={status}, user={res.get('user')}")
    assert status == 200, "Admin login failed"
    admin_token = res["access_token"]
    assert res["user"]["role"] == "ADMIN"

    print("\n=== 4. Testing Product Listing ===")
    status, products = request("/api/products")
    print(f"Fetched {len(products)} products")
    assert len(products) >= 10, f"Expected 10 products, got {len(products)}"
    hygiene_prod = next((p for p in products if not p.get("is_returnable")), None)
    print(f"Hygiene non-returnable item: {hygiene_prod['title'] if hygiene_prod else 'None'}")
    assert hygiene_prod is not None, "Hygiene non-returnable item not found"

    print("\n=== 5. Testing Order Placement ===")
    status, order = request("/api/orders", method="POST", token=customer_token, data={
        "items": [
            {"productId": products[0]["id"], "selectedSize": "9 UK", "quantity": 1}
        ],
        "shippingAddress": "12A Indiranagar, Bengaluru, KA 560038",
        "phone": "+91 98450 12891",
        "paymentMethod": "MOCK_UPI"
    })
    print(f"Order created: status={status}, order_number={order.get('order_number')}")
    assert status == 200, f"Failed to place order: {order}"
    order_id = order["id"]

    print("\n=== 6. Testing Order Tracking ===")
    status, tracking = request(f"/api/orders/{order_id}/tracking", token=customer_token)
    print(f"Tracking: status={status}, events_count={len(tracking.get('events', []))}")
    assert status == 200, "Failed to get tracking"

    print("\n=== 7. Testing AI Support Agent Conversation (Gemini 3.5 Flash) ===")
    chat_prompt = "Hi, I just placed an order. Can you tell me where it is right now?"
    status, chat_res = request("/api/chat", method="POST", token=customer_token, data={
        "message": chat_prompt,
        "orderId": order_id
    })
    print(f"AI Agent Status: {status}")
    print(f"AI Agent Reply: {chat_res.get('replyText')}")
    print(f"AI Detected Intent: {chat_res.get('intent')}, Sentiment: {chat_res.get('sentiment')}")
    assert status == 200, f"AI Chat failed: {chat_res}"
    assert chat_res.get("replyText"), "Empty AI reply"

    print("\n=== 8. Testing Admin Dashboard & Analytics ===")
    status, dash = request("/api/admin/dashboard", token=admin_token)
    print(f"Admin Dashboard KPIs: {dash.get('kpis')}")
    assert status == 200, "Failed to load admin dashboard"

    print("\n==========================================")
    print("ALL TESTS PASSED SUCCESSFULLY! EVERYTHING LIVE & WORKING!")
    print("==========================================")

if __name__ == "__main__":
    run_tests()
