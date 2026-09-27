from tests.conftest import register


async def test_register_login_me(client):
    headers = await register(client)
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["role"] == "owner"
    assert body["organization"]["name"] == "Acme Plumbing"

    login = await client.post("/api/auth/login", json={"email": "OWNER@acme-example.com", "password": "supersecret123"})
    assert login.status_code == 200
    assert login.json()["access_token"]


async def test_register_creates_default_agent(client):
    headers = await register(client)
    agents = (await client.get("/api/agents", headers=headers)).json()
    assert len(agents) == 1
    assert "book_appointment" in agents[0]["allowed_actions"]


async def test_duplicate_email_rejected(client):
    await register(client)
    r = await client.post("/api/auth/register", json={
        "organization_name": "Other", "full_name": "X", "email": "owner@acme-example.com", "password": "supersecret123",
    })
    assert r.status_code == 409


async def test_weak_password_rejected(client):
    r = await client.post("/api/auth/register", json={
        "organization_name": "Other", "full_name": "X", "email": "a@b-example.com", "password": "short",
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_bad_login(client):
    await register(client)
    r = await client.post("/api/auth/login", json={"email": "owner@acme-example.com", "password": "wrong-password1"})
    assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": "nobody@acme-example.com", "password": "wrong-password1"})
    assert r.status_code == 401


async def test_requires_auth(client):
    assert (await client.get("/api/agents")).status_code == 401
    bad = await client.get("/api/agents", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401


async def test_role_permissions(client):
    owner = await register(client)
    r = await client.post("/api/users", headers=owner, json={
        "email": "viewer@acme-example.com", "full_name": "Vic", "role": "viewer", "password": "viewerpass123",
    })
    assert r.status_code == 201
    login = await client.post("/api/auth/login", json={"email": "viewer@acme-example.com", "password": "viewerpass123"})
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}

    agent_id = (await client.get("/api/agents", headers=viewer)).json()[0]["id"]
    assert (await client.patch(f"/api/agents/{agent_id}", headers=viewer, json={"name": "Hax"})).status_code == 403
    assert (await client.get("/api/users", headers=viewer)).status_code == 403
    assert (await client.patch(f"/api/agents/{agent_id}", headers=owner, json={"name": "Nova"})).json()["name"] == "Nova"


async def test_admin_cannot_promote_to_owner(client):
    owner = await register(client)
    await client.post("/api/users", headers=owner, json={
        "email": "admin@acme-example.com", "full_name": "Ad", "role": "admin", "password": "adminpass123",
    })
    login = await client.post("/api/auth/login", json={"email": "admin@acme-example.com", "password": "adminpass123"})
    admin = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = await client.post("/api/users", headers=admin, json={
        "email": "o2@acme-example.com", "full_name": "O2", "role": "owner", "password": "ownerpass123",
    })
    assert r.status_code == 403


async def test_tenant_isolation(client):
    a = await register(client, email="a@a-example.com", org="Org A")
    b = await register(client, email="b@b-example.com", org="Org B")
    agent_a = (await client.get("/api/agents", headers=a)).json()[0]["id"]
    assert (await client.get(f"/api/agents/{agent_a}", headers=b)).status_code == 404
    assert (await client.patch(f"/api/agents/{agent_a}", headers=b, json={"name": "x"})).status_code == 404


async def test_agent_validation(client):
    h = await register(client)
    agent_id = (await client.get("/api/agents", headers=h)).json()[0]["id"]
    r = await client.patch(f"/api/agents/{agent_id}", headers=h, json={"allowed_actions": ["launch_missiles"]})
    assert r.status_code == 422
    r = await client.patch(f"/api/agents/{agent_id}", headers=h, json={"transfer_enabled": True})
    assert r.status_code == 400 and r.json()["error"]["code"] == "transfer_number_required"
    r = await client.patch(f"/api/agents/{agent_id}", headers=h, json={"working_hours": {"mon": [["18:00", "09:00"]]}})
    assert r.status_code == 422
    r = await client.patch(f"/api/agents/{agent_id}", headers=h, json={"transfer_enabled": True, "transfer_number": "+1 (555) 010-2000"})
    assert r.status_code == 200 and r.json()["transfer_number"] == "+15550102000"


async def test_audit_log_written(client):
    h = await register(client)
    logs = (await client.get("/api/audit-logs", headers=h)).json()
    assert any(entry["action"] == "org.registered" for entry in logs)
