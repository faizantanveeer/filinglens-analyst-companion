import os
import tempfile

# Point the app at a throwaway data dir before any backend module is imported.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="filinglens-test-")


def guest_headers(client) -> dict:
    """A fresh guest session (what every visitor gets on first load)."""
    r = client.post("/auth/guest")
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def user_headers(client, email: str, password: str = "Correct-Horse-9") -> dict:
    """Sign up (or log in if the account exists) and return auth headers."""
    r = client.post("/auth/signup", json={"email": email, "password": password})
    if r.status_code == 409:
        r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
