"""End-to-end API tests for the main flows, now using JWT tokens. Run top to bottom."""
from decimal import Decimal

from app.tests.conftest import USER


# ---------- Users ----------
def test_register_hides_password(registered_user):
    assert "password" not in registered_user                   # never returned
    assert registered_user["email"] == USER["email"]


def test_register_duplicate_email(client, registered_user):
    r = client.post("/api/users/register", json=USER)
    assert r.status_code == 409


def test_register_invalid_mobile(client):
    r = client.post("/api/users/register", json={**USER, "email": "m@example.com", "mobile": "12345"})
    assert r.status_code == 422


# ---------- Auth ----------
def test_login_returns_token(client, registered_user):
    r = client.post("/api/auth/login", json={"email": USER["email"], "password": USER["password"]})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"].count(".") == 2                # header.payload.signature


def test_login_wrong_password(client, registered_user):
    r = client.post("/api/auth/login", json={"email": USER["email"], "password": "wrongpass1"})
    assert r.status_code == 401


def test_me_returns_logged_in_user(client, auth_headers):
    r = client.get("/api/users/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == USER["email"]
    assert "password" not in r.json()


# ---------- Products (public: no token needed) ----------
def test_list_categories(client):
    r = client.get("/api/categories")
    assert r.status_code == 200
    assert len(r.json()) > 0


def test_list_products(client):
    r = client.get("/api/products")
    assert r.status_code == 200
    assert len(r.json()) > 0


def test_product_not_found(client):
    assert client.get("/api/products/99999").status_code == 404


def test_search_by_name(client):
    first = client.get("/api/products").json()[0]
    r = client.get("/api/products/search", params={"name": first["product_name"][:4]})   # search by part of a real name
    assert r.status_code == 200
    assert any(p["product_id"] == first["product_id"] for p in r.json())


# ---------- Cart (needs a token) ----------
def test_add_to_cart_more_than_stock(client, auth_headers):
    r = client.post("/api/cart/add", json={"product_id": 1, "quantity": 10000}, headers=auth_headers)
    assert r.status_code == 400


def test_add_to_cart_zero_quantity(client, auth_headers):
    r = client.post("/api/cart/add", json={"product_id": 1, "quantity": 0}, headers=auth_headers)
    assert r.status_code == 422


def test_add_unknown_product(client, auth_headers):
    r = client.post("/api/cart/add", json={"product_id": 99999, "quantity": 1}, headers=auth_headers)
    assert r.status_code == 404


# ---------- Orders (needs a token) ----------
def test_checkout_empty_cart(client, auth_headers):
    r = client.post("/api/orders/checkout", json={"payment_method": "UPI"}, headers=auth_headers)
    assert r.status_code == 400


def test_checkout_invalid_payment_method(client, auth_headers):
    r = client.post("/api/orders/checkout", json={"payment_method": "BITCOIN"}, headers=auth_headers)
    assert r.status_code == 422


def test_checkout_calculates_total_and_empties_cart(client, auth_headers):
    price = Decimal(str(client.get("/api/products/1").json()["price"]))
    client.post("/api/cart/add", json={"product_id": 1, "quantity": 2}, headers=auth_headers)

    r = client.post("/api/orders/checkout", json={"payment_method": "UPI"}, headers=auth_headers)
    assert r.status_code == 201
    assert Decimal(str(r.json()["total_amount"])) == price * 2         # server calculated the total
    assert client.get("/api/cart", headers=auth_headers).json() == []  # cart emptied


def test_my_order_history_and_details(client, auth_headers):
    orders = client.get("/api/orders/me", headers=auth_headers).json()
    assert len(orders) >= 1
    r = client.get(f"/api/orders/details/{orders[0]['order_id']}", headers=auth_headers)
    assert r.status_code == 200
