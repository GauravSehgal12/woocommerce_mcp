import { useCallback, useEffect, useState } from "react";

import Chat from "./Chat.jsx";

import {
  Activity,
  AlertCircle,
  CheckCircle2,
  CirclePlus,
  Clock3,
  Database,
  ExternalLink,
  LoaderCircle,
  LogOut,
  Network,
  RefreshCw,
  Server,
  ShieldCheck,
  ShieldAlert,
  Trash2,
  Users,
  UserPlus,
  KeyRound,
  Copy,
  LockKeyhole,
  XCircle,
  Bot,
} from "lucide-react";

import "./App.css";
import AuditLogs from "./AuditLogs";

const API_BASE =
  import.meta.env.VITE_API_BASE || "http://127.0.0.1:8101";

const API_OPTIONS = { credentials: "include" };

function formatDate(value) {
  if (!value) return "Not checked yet";

  const date = new Date(value);

  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function StatusBadge({ status }) {
  const normalized = (status || "unknown").toLowerCase();

  return (
    <span className={`status-badge status-${normalized}`}>
      <span className="status-dot" />

      {normalized}
    </span>
  );
}

function StatCard({ label, value, icon: Icon, tone }) {
  return (
    <div className="stat-card">
      <div className={`stat-icon ${tone}`}>
        <Icon size={21} />
      </div>

      <div>
        <p className="stat-label">{label}</p>

        <p className="stat-value">{value}</p>
      </div>
    </div>
  );
}

function App() {
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState("");

  const [servers, setServers] = useState([]);

  const [health, setHealth] = useState([]);

  const [loading, setLoading] = useState(true);

  const [refreshing, setRefreshing] = useState(false);

  const [error, setError] = useState("");

  const [actionMessage, setActionMessage] = useState("");

  const [busyId, setBusyId] = useState("");

  const [showForm, setShowForm] = useState(false);

  const [activePage, setActivePage] = useState("overview");
  const [users, setUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [memberForm, setMemberForm] = useState({ username: "", password: "" });
  const [memberBusy, setMemberBusy] = useState(false);
  const [memberError, setMemberError] = useState("");
  const [memberSuccess, setMemberSuccess] = useState("");
  const [keysByUser, setKeysByUser] = useState({});
  const [keysLoadingFor, setKeysLoadingFor] = useState("");
  const [keyBusy, setKeyBusy] = useState("");
  const [newSecret, setNewSecret] = useState(null);
  const [availableTools, setAvailableTools] = useState([]);
  const [toolWarnings, setToolWarnings] = useState([]);
  const [editingKey, setEditingKey] = useState(null);
  const [selectedTools, setSelectedTools] = useState([]);
  const [permissionsBusy, setPermissionsBusy] = useState(false);
  const [permissionError, setPermissionError] = useState("");
  const [permissionSuccess, setPermissionSuccess] = useState("");

  const [form, setForm] = useState({
    name: "",

    url: "",

    description: "",
  });

  const loadDashboard = useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);

    try {
      const [serversResponse, healthResponse] = await Promise.all([
        fetch(`${API_BASE}/servers`, API_OPTIONS),
        fetch(`${API_BASE}/servers/health`, API_OPTIONS),
      ]);

      if (serversResponse.status === 401 || healthResponse.status === 401) {
        setUser(null);
        setServers([]);
        setHealth([]);
        return;
      }
      if (!serversResponse.ok || !healthResponse.ok) {
        throw new Error("The Registry API returned an error.");
      }

      const serversData = await serversResponse.json();

      const healthData = await healthResponse.json();

      setServers(serversData.servers || []);

      setHealth(healthData.servers || []);

      setError("");
    } catch (err) {
      setError(
        `Cannot connect to the Registry API. ${err.message} ` +
          "Check that the API is running on port 8101.",
      );
    } finally {
      setLoading(false);

      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function restoreSession() {
      try {
        const response = await fetch(`${API_BASE}/auth/me`, API_OPTIONS);
        if (!response.ok) return;
        const data = await response.json();
        if (!cancelled) setUser(data.user || data);
      } catch {
        if (!cancelled)
          setLoginError(
            "Cannot reach the Registry API. Check that it is running on port 8101.",
          );
      } finally {
        if (!cancelled) setAuthChecking(false);
      }
    }
    restoreSession();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    loadDashboard();
    const timer = setInterval(() => loadDashboard(), 5000);
    return () => clearInterval(timer);
  }, [loadDashboard, user]);

  async function handleLogin(event) {
    event.preventDefault();
    setLoginBusy(true);
    setLoginError("");
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: loginUsername.trim(),
          password: loginPassword,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(
          data.detail || "Login failed. Check your username and password.",
        );
      const meResponse = await fetch(`${API_BASE}/auth/me`, API_OPTIONS);
      if (!meResponse.ok)
        throw new Error(
          "Login succeeded, but the session could not be verified.",
        );
      const me = await meResponse.json();
      setUser(me.user || me || data.user || data);
      setLoginPassword("");
      setError("");
    } catch (err) {
      setLoginError(err.message || "Could not sign in.");
    } finally {
      setLoginBusy(false);
    }
  }

  async function handleLogout() {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        ...API_OPTIONS,
      });
    } finally {
      setUser(null);
      setServers([]);
      setHealth([]);
      setShowForm(false);
      setActivePage("overview");
    }
  }

  const healthById = Object.fromEntries(
    health.map((item) => [item.server_id, item]),
  );

  const healthyCount = servers.filter(
    (server) => server.enabled && healthById[server.id]?.status === "healthy",
  ).length;

  const unhealthyCount = servers.filter(
    (server) => server.enabled && healthById[server.id]?.status === "unhealthy",
  ).length;

  const totalTools = servers.reduce((total, server) => {
    if (!server.enabled) return total;

    return total + (healthById[server.id]?.discovered_tools_count || 0);
  }, 0);

  async function performAction(server, action) {
    const labels = {
      enable: "enabled",

      disable: "disabled",

      delete: "removed",
    };

    const confirmed =
      action !== "delete" ||
      window.confirm(`Remove "${server.name}" from the registry?`);

    if (!confirmed) return;

    setBusyId(server.id);

    setActionMessage("");

    setError("");

    try {
      const response = await fetch(
        `${API_BASE}/servers/${server.id}` +
          (action === "delete" ? "" : `/${action}`),

        {
          ...API_OPTIONS,
          method: action === "delete" ? "DELETE" : "PATCH",
        },
      );

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail || "The operation failed.");
      }

      setActionMessage(`${server.name} ${labels[action]} successfully.`);

      await loadDashboard();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId("");
    }
  }

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    setMemberError("");
    try {
      const response = await fetch(`${API_BASE}/users`, API_OPTIONS);
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(result.detail || "Could not load platform users.");
      }
      setUsers(result.users || []);
    } catch (err) {
      setMemberError(err.message || "Could not load platform users.");
    } finally {
      setUsersLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user?.role === "admin" && activePage === "users") {
      loadUsers();
    }
  }, [user, activePage, loadUsers]);

  async function createMember(event) {
    event.preventDefault();
    setMemberBusy(true);
    setMemberError("");
    setMemberSuccess("");
    try {
      const response = await fetch(`${API_BASE}/users`, {
        method: "POST",
        ...API_OPTIONS,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: memberForm.username.trim(),
          role: "member",
          password: memberForm.password,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          result.detail || "Could not create the member account.",
        );
      }
      setMemberForm({ username: "", password: "" });
      setMemberSuccess(
        `Member "${result.username || memberForm.username.trim()}" created successfully.`,
      );
      await loadUsers();
    } catch (err) {
      setMemberError(err.message || "Could not create the member account.");
    } finally {
      setMemberBusy(false);
    }
  }

  async function loadUserKeys(userId) {
    setKeysLoadingFor(userId);
    setMemberError("");
    try {
      const response = await fetch(
        `${API_BASE}/users/${userId}/api-keys`,
        API_OPTIONS,
      );
      const result = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(result.detail || "Could not load API keys.");
      setKeysByUser((previous) => ({
        ...previous,
        [userId]: result.api_keys || [],
      }));
    } catch (err) {
      setMemberError(err.message || "Could not load API keys.");
    } finally {
      setKeysLoadingFor("");
    }
  }

  async function generateMemberKey(account) {
    setKeyBusy(account.id);
    setMemberError("");
    setMemberSuccess("");
    setNewSecret(null);
    try {
      const response = await fetch(`${API_BASE}/users/${account.id}/api-keys`, {
        method: "POST",
        ...API_OPTIONS,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(result.detail || "Could not generate API key.");
      setNewSecret({
        username: account.username,
        keyId: result.key_id,
        key: result.api_key,
        prefix: result.key_prefix,
      });
      setMemberSuccess(
        `API key generated for ${account.username}. Copy it now; the full secret is shown only once.`,
      );
      await loadUserKeys(account.id);
      await openPermissions(
        account,
        {
          id: result.key_id,
          key_prefix: result.key_prefix,
          created_at: new Date().toISOString(),
          revoked_at: null,
        },
        true,
      );
    } catch (err) {
      setMemberError(err.message || "Could not generate API key.");
    } finally {
      setKeyBusy("");
    }
  }

  async function revokeMemberKey(account, key) {
    if (
      !window.confirm(
        `Revoke API key ${key.key_prefix} for ${account.username}? This cannot be undone.`,
      )
    )
      return;
    setKeyBusy(key.id);
    setMemberError("");
    try {
      const response = await fetch(`${API_BASE}/api-keys/${key.id}/revoke`, {
        method: "POST",
        ...API_OPTIONS,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(result.detail || "Could not revoke API key.");
      setMemberSuccess(`API key ${key.key_prefix} revoked.`);
      await loadUserKeys(account.id);
      if (editingKey?.id === key.id) setEditingKey(null);
    } catch (err) {
      setMemberError(err.message || "Could not revoke API key.");
    } finally {
      setKeyBusy("");
    }
  }

  async function openPermissions(account, key, skipFetch = false) {
    setPermissionError("");
    setPermissionSuccess("");
    setEditingKey({ ...key, username: account.username, userId: account.id });
    setSelectedTools([]);
    try {
      const [toolsResponse, permissionsResponse] = await Promise.all([
        fetch(`${API_BASE}/available-tools`, API_OPTIONS),
        skipFetch
          ? Promise.resolve(null)
          : fetch(`${API_BASE}/api-keys/${key.id}/permissions`, API_OPTIONS),
      ]);
      const toolsResult = await toolsResponse.json().catch(() => ({}));
      if (!toolsResponse.ok)
        throw new Error(
          toolsResult.detail || "Could not discover available tools.",
        );
      setAvailableTools(toolsResult.tools || []);
      setToolWarnings(toolsResult.warnings || []);
      if (permissionsResponse) {
        const permissionsResult = await permissionsResponse
          .json()
          .catch(() => ({}));
        if (!permissionsResponse.ok)
          throw new Error(
            permissionsResult.detail || "Could not load key permissions.",
          );
        setSelectedTools(permissionsResult.tools || []);
      }
    } catch (err) {
      setPermissionError(err.message || "Could not load tool permissions.");
    }
  }

  async function saveKeyPermissions(event) {
    event.preventDefault();
    if (!editingKey) return;
    setPermissionsBusy(true);
    setPermissionError("");
    setPermissionSuccess("");
    try {
      const response = await fetch(
        `${API_BASE}/api-keys/${editingKey.id}/permissions`,
        {
          method: "PUT",
          ...API_OPTIONS,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tools: selectedTools }),
        },
      );
      const result = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(result.detail || "Could not save tool permissions.");
      setSelectedTools(result.tools || []);
      setPermissionSuccess(
        `Saved ${result.count} permitted tool${result.count === 1 ? "" : "s"} for ${editingKey.username}.`,
      );
    } catch (err) {
      setPermissionError(err.message || "Could not save tool permissions.");
    } finally {
      setPermissionsBusy(false);
    }
  }

  function toggleSelectedTool(toolName, checked) {
    setSelectedTools((previous) =>
      checked
        ? [...new Set([...previous, toolName])]
        : previous.filter((name) => name !== toolName),
    );
  }

  async function addServer(event) {
    event.preventDefault();

    setBusyId("new");

    setError("");

    setActionMessage("");

    try {
      const response = await fetch(`${API_BASE}/servers`, {
        method: "POST",

        ...API_OPTIONS,
        headers: { "Content-Type": "application/json" },

        body: JSON.stringify({
          name: form.name.trim(),

          url: form.url.trim(),

          description: form.description.trim(),
        }),
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail || "Could not register the server.");
      }

      setForm({ name: "", url: "", description: "" });

      setShowForm(false);

      setActionMessage(`${result.server.name} registered successfully.`);

      await loadDashboard();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId("");
    }
  }

  if (authChecking) {
    return (
      <div
        className="app-shell"
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: 24,
        }}
      >
        <main className="main-content" style={{ width: "100%", maxWidth: 440 }}>
          <section className="panel empty-state">
            <LoaderCircle className="spin" size={28} />
            <p>Checking your session...</p>
          </section>
        </main>
      </div>
    );
  }

  if (!user) {
    return (
      <div
        className="app-shell"
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: 24,
        }}
      >
        <main className="main-content" style={{ width: "100%", maxWidth: 440 }}>
          <section className="panel" style={{ padding: 32 }}>
            <div className="brand" style={{ marginBottom: 24 }}>
              <div className="brand-icon">
                <Network size={23} />
              </div>
              <div>
                <h2>MCP Console</h2>
                <span>Sign in to manage your gateway</span>
              </div>
            </div>
            <h1 style={{ marginBottom: 8 }}>Welcome back</h1>
            <p className="page-subtitle" style={{ marginBottom: 24 }}>
              Use your platform account to continue.
            </p>
            {loginError && (
              <div className="notice notice-error">
                <AlertCircle size={18} />
                <span>{loginError}</span>
              </div>
            )}
            <form className="server-form" onSubmit={handleLogin}>
              <label>
                Username
                <input
                  autoComplete="username"
                  required
                  value={loginUsername}
                  onChange={(e) => setLoginUsername(e.target.value)}
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                />
              </label>
              <button
                className="button button-primary"
                disabled={loginBusy}
                style={{ width: "100%", justifyContent: "center" }}
              >
                {loginBusy ? <LoaderCircle size={16} className="spin" /> : null}
                {loginBusy ? "Signing in..." : "Sign in"}
              </button>
            </form>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">
            <Network size={23} />
          </div>

          <div>
            <h2>MCP Console</h2>

            <span>Gateway management</span>
          </div>
        </div>

        <div className="nav-section-label">WORKSPACE</div>

        <button
          type="button"
          className={`nav-item ${activePage === "overview" ? "active" : ""}`}
          onClick={() => setActivePage("overview")}
        >
          <Activity size={18} />
          <span>Overview</span>
        </button>
        <button
          type="button"
          className={`nav-item ${activePage === "servers" ? "active" : ""}`}
          onClick={() => setActivePage("servers")}
        >
          <Server size={18} />
          <span>MCP Servers</span>
          <span className="nav-count">{servers.length}</span>
        </button>
        {user?.role === "admin" && (
          <button
            type="button"
            className={`nav-item ${activePage === "users" ? "active" : ""}`}
            onClick={() => setActivePage("users")}
          >
            <Users size={18} />
            <span>User Management</span>
            <span className="nav-count">{users.length}</span>
          </button>
        )}
        <button
          type="button"
          className={`nav-item ${activePage === "audit" ? "active" : ""}`}
          onClick={() => setActivePage("audit")}
        >
          <ShieldCheck size={18} />
          <span>Audit Logs</span>
        </button>
        <button
          type="button"
          className={`nav-item ${activePage === "chat" ? "active" : ""}`}
          onClick={() => setActivePage("chat")}
        >
          <Bot size={18} />
          <span>Chat Assistant</span>
        </button>

        <div className="sidebar-bottom">
          <div className="connection-indicator">
            <span className="connection-dot" />

            <div>
              <strong>Registry API</strong>

              <span>127.0.0.1:8101</span>
            </div>
          </div>

          <p>WooCommerce MCP Platform</p>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <div className="breadcrumb">
              Workspace /{" "}
              {activePage === "chat"
                ? "Chat Assistant"
                : activePage === "audit"
                  ? "Audit Logs"
                  : activePage === "servers"
                    ? "MCP Servers"
                    : activePage === "users"
                      ? "User Management"
                      : "Overview"}
            </div>

            <h1>
              {activePage === "chat"
                ? "Chat Assistant"
                : activePage === "audit"
                  ? "Audit Logs"
                  : activePage === "servers"
                    ? "MCP Servers"
                    : activePage === "users"
                      ? "User Management"
                      : "Server Dashboard"}
            </h1>

            <p className="page-subtitle">
              {activePage === "chat"
                ? "Ask questions about your connected MCP tools and store data."
                : activePage === "audit"
                  ? "Review authenticated tool activity and execution outcomes."
                  : activePage === "users"
                    ? "Manage member API keys and per-key tool permissions."
                    : "Monitor and manage your connected MCP servers."}
            </p>
          </div>

          <div className="topbar-actions">
            <span className="refresh-label">
              {user.username || user.email || "Signed in"} ·{" "}
              {user.role || "member"}
            </span>
            <button className="button button-secondary" onClick={handleLogout}>
              <LogOut size={16} /> Sign out
            </button>
            {activePage === "overview" && user?.role === "admin" && (
              <>
                <span className="refresh-label">
                  <span className="connection-dot" />
                  Auto-refresh: 5 seconds
                </span>

                <button
                  className="button button-secondary"

                  onClick={() => loadDashboard(true)}

                  disabled={refreshing}
                >
                  <RefreshCw
                    size={16}

                    className={refreshing ? "spin" : ""}
                  />
                  Refresh
                </button>

                <button
                  className="button button-primary"

                  onClick={() => setShowForm(!showForm)}
                >
                  <CirclePlus size={17} />
                  Add server
                </button>
              </>
            )}
          </div>
        </header>

        {activePage === "users" && user?.role === "admin" ? (
          <section className="panel">
            <div className="section-heading">
              <div>
                <h2>Create a member account</h2>
                <p>
                  Members can sign in with these credentials. Passwords must
                  contain at least 12 characters.
                </p>
              </div>
              <UserPlus size={22} />
            </div>
            {memberError && (
              <div className="notice notice-error">
                <AlertCircle size={18} />
                <span>{memberError}</span>
                <button type="button" onClick={() => setMemberError("")}>
                  Dismiss
                </button>
              </div>
            )}
            {memberSuccess && (
              <div className="notice notice-success">
                <CheckCircle2 size={18} />
                <span>{memberSuccess}</span>
                <button type="button" onClick={() => setMemberSuccess("")}>
                  Dismiss
                </button>
              </div>
            )}
            <form className="server-form" onSubmit={createMember}>
              <label>
                Username
                <input
                  required
                  minLength={1}
                  maxLength={80}
                  autoComplete="off"
                  value={memberForm.username}
                  onChange={(e) =>
                    setMemberForm({ ...memberForm, username: e.target.value })
                  }
                  placeholder="e.g. store_operator"
                />
              </label>
              <label>
                Temporary password
                <input
                  required
                  minLength={12}
                  maxLength={1024}
                  type="password"
                  autoComplete="new-password"
                  value={memberForm.password}
                  onChange={(e) =>
                    setMemberForm({ ...memberForm, password: e.target.value })
                  }
                  placeholder="At least 12 characters"
                />
              </label>
              <div className="form-actions">
                <button
                  type="submit"
                  className="button button-primary"
                  disabled={memberBusy}
                >
                  {memberBusy ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <UserPlus size={16} />
                  )}
                  {memberBusy ? "Creating member..." : "Create member"}
                </button>
              </div>
            </form>
            <div className="section-heading" style={{ marginTop: 32 }}>
              <div>
                <h2>Platform accounts</h2>
                <p>
                  {users.length} account{users.length === 1 ? "" : "s"}{" "}
                  registered
                </p>
              </div>
              <button
                type="button"
                className="button button-secondary"
                onClick={loadUsers}
                disabled={usersLoading}
              >
                <RefreshCw size={15} className={usersLoading ? "spin" : ""} />{" "}
                Refresh
              </button>
            </div>
            {usersLoading ? (
              <div className="empty-state">
                <LoaderCircle size={24} className="spin" />
                <p>Loading users...</p>
              </div>
            ) : users.length === 0 ? (
              <div className="empty-state">
                <Users size={28} />
                <p>No platform accounts were returned.</p>
              </div>
            ) : (
              <div className="server-list">
                {users.map((account) => (
                  <article className="server-card" key={account.id}>
                    <div className="server-card-top">
                      <div className="server-identity">
                        <div className="server-icon">
                          <Users size={20} />
                        </div>
                        <div>
                          <div className="server-title-row">
                            <h3>{account.username}</h3>
                            <StatusBadge
                              status={account.active ? "active" : "disabled"}
                            />
                          </div>
                          <p className="server-description">
                            Role: {account.role}
                          </p>
                          <p className="server-description">
                            Created: {formatDate(account.created_at)}
                          </p>
                        </div>
                      </div>
                      {account.role === "member" && (
                        <div className="server-actions">
                          <button
                            type="button"
                            className="button button-primary button-small"
                            onClick={() => generateMemberKey(account)}
                            disabled={keyBusy === account.id || !account.active}
                          >
                            {keyBusy === account.id ? (
                              <LoaderCircle size={15} className="spin" />
                            ) : (
                              <KeyRound size={15} />
                            )}{" "}
                            Generate API key
                          </button>
                          <button
                            type="button"
                            className="button button-secondary button-small"
                            onClick={() => loadUserKeys(account.id)}
                            disabled={keysLoadingFor === account.id}
                          >
                            <RefreshCw
                              size={15}
                              className={
                                keysLoadingFor === account.id ? "spin" : ""
                              }
                            />{" "}
                            Load keys
                          </button>
                        </div>
                      )}
                    </div>
                    {account.role === "member" && (
                      <div style={{ marginTop: 16 }}>
                        {(keysByUser[account.id] || []).length === 0 ? (
                          <p className="server-description">
                            No API keys loaded or no keys have been issued yet.
                          </p>
                        ) : (
                          <div className="server-list">
                            {(keysByUser[account.id] || []).map((key) => (
                              <div
                                className="panel"
                                key={key.id}
                                style={{ padding: 14 }}
                              >
                                <div className="server-card-top">
                                  <div>
                                    <strong>{key.key_prefix}</strong>
                                    <p className="server-description">
                                      Created: {formatDate(key.created_at)}
                                    </p>
                                    <p className="server-description">
                                      Status:{" "}
                                      {key.revoked_at ? "Revoked" : "Active"}
                                    </p>
                                  </div>
                                  <div className="server-actions">
                                    {!key.revoked_at && (
                                      <button
                                        type="button"
                                        className="button button-secondary button-small"
                                        onClick={() =>
                                          openPermissions(account, key)
                                        }
                                      >
                                        <LockKeyhole size={15} /> Configure
                                        tools
                                      </button>
                                    )}
                                    {!key.revoked_at && (
                                      <button
                                        type="button"
                                        className="button button-secondary button-small"
                                        onClick={() =>
                                          revokeMemberKey(account, key)
                                        }
                                        disabled={keyBusy === key.id}
                                      >
                                        {keyBusy === key.id ? (
                                          <LoaderCircle
                                            size={15}
                                            className="spin"
                                          />
                                        ) : (
                                          <ShieldCheck size={15} />
                                        )}{" "}
                                        Revoke
                                      </button>
                                    )}
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
            {newSecret && (
              <div className="panel" style={{ marginTop: 20, padding: 16 }}>
                <div className="section-heading">
                  <div>
                    <h3>New API key for {newSecret.username}</h3>
                    <p>Copy this secret now. It cannot be retrieved later.</p>
                  </div>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => setNewSecret(null)}
                    aria-label="Hide generated API key"
                  >
                    <XCircle size={18} />
                  </button>
                </div>
                <code
                  style={{
                    display: "block",
                    overflowWrap: "anywhere",
                    padding: 12,
                  }}
                >
                  {newSecret.key}
                </code>
                <div className="form-actions" style={{ marginTop: 12 }}>
                  <button
                    type="button"
                    className="button button-primary"
                    onClick={() => {
                      navigator.clipboard
                        .writeText(newSecret.key)
                        .then(() =>
                          setMemberSuccess("API key copied to clipboard."),
                        )
                        .catch(() =>
                          setMemberError(
                            "Clipboard access failed; select and copy the key manually.",
                          ),
                        );
                    }}
                  >
                    <Copy size={15} /> Copy API key
                  </button>
                </div>
              </div>
            )}
            {editingKey && (
              <section className="panel form-panel" style={{ marginTop: 20 }}>
                <div className="section-heading">
                  <div>
                    <h2>Tool permissions</h2>
                    <p>
                      Key {editingKey.key_prefix || editingKey.id} for{" "}
                      {editingKey.username}. Members can call only explicitly
                      selected tools. An empty selection denies all tools.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => setEditingKey(null)}
                    aria-label="Close tool permissions"
                  >
                    <XCircle size={20} />
                  </button>
                </div>
                {permissionError && (
                  <div className="notice notice-error">
                    <AlertCircle size={18} />
                    <span>{permissionError}</span>
                  </div>
                )}
                {permissionSuccess && (
                  <div className="notice notice-success">
                    <CheckCircle2 size={18} />
                    <span>{permissionSuccess}</span>
                  </div>
                )}
                {toolWarnings.length > 0 && (
                  <div className="notice notice-error">
                    <AlertCircle size={18} />
                    <span>
                      Some MCP servers could not be queried. Tools from those
                      servers may be missing until they are healthy.
                    </span>
                  </div>
                )}
                {availableTools.length === 0 ? (
                  <div className="empty-state">
                    <ShieldAlert size={26} />
                    <p>
                      No tools discovered. Confirm enabled MCP servers are
                      running, then reopen this editor.
                    </p>
                  </div>
                ) : (
                  <form className="server-form" onSubmit={saveKeyPermissions}>
                    <div style={{ display: "grid", gap: 12 }}>
                      {availableTools.map((tool) => (
                        <label
                          key={tool.name}
                          style={{
                            display: "flex",
                            alignItems: "flex-start",
                            gap: 10,
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={selectedTools.includes(tool.name)}
                            onChange={(event) =>
                              toggleSelectedTool(
                                tool.name,
                                event.target.checked,
                              )
                            }
                          />
                          <span>
                            <strong>{tool.name}</strong>
                            <span style={{ display: "block", opacity: 0.75 }}>
                              {tool.description ||
                                `Tool on ${tool.server_name}`}
                            </span>
                          </span>
                        </label>
                      ))}
                    </div>
                    <div className="form-actions">
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() =>
                          setSelectedTools(
                            availableTools.map((tool) => tool.name),
                          )
                        }
                      >
                        Select all
                      </button>
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => setSelectedTools([])}
                      >
                        Clear all
                      </button>
                      <button
                        type="submit"
                        className="button button-primary"
                        disabled={permissionsBusy}
                      >
                        {permissionsBusy ? (
                          <LoaderCircle size={15} className="spin" />
                        ) : (
                          <LockKeyhole size={15} />
                        )}
                        {permissionsBusy ? "Saving..." : "Save permissions"}
                      </button>
                    </div>
                  </form>
                )}
              </section>
            )}
          </section>
        ) : activePage === "chat" ? (
          <Chat />
        ) : activePage === "audit" ? (
          <AuditLogs />
        ) : (
          <>
            {error && (
              <div className="notice notice-error">
                <AlertCircle size={18} />

                <span>{error}</span>

                <button onClick={() => setError("")}>Dismiss</button>
              </div>
            )}

            {actionMessage && (
              <div className="notice notice-success">
                <CheckCircle2 size={18} />

                <span>{actionMessage}</span>

                <button onClick={() => setActionMessage("")}>Dismiss</button>
              </div>
            )}

            {showForm && user?.role === "admin" && (
              <section className="panel form-panel">
                <div className="section-heading">
                  <div>
                    <h2>Register an MCP server</h2>

                    <p>Add an upstream Streamable HTTP MCP endpoint.</p>
                  </div>

                  <button
                    className="icon-button"

                    onClick={() => setShowForm(false)}

                    aria-label="Close form"
                  >
                    <XCircle size={20} />
                  </button>
                </div>

                <form onSubmit={addServer} className="server-form">
                  <label>
                    Server name
                    <input
                      required

                      minLength={2}

                      maxLength={80}

                      pattern="[A-Za-z0-9][A-Za-z0-9\_-]\*"

                      placeholder="e.g. inventory"

                      value={form.name}

                      onChange={(e) =>
                        setForm({ ...form, name: e.target.value })
                      }
                    />
                  </label>

                  <label>
                    MCP endpoint URL
                    <input
                      required

                      type="url"

                      placeholder="http://127.0.0.1:8200/mcp"

                      value={form.url}

                      onChange={(e) =>
                        setForm({ ...form, url: e.target.value })
                      }
                    />
                  </label>

                  <label>
                    Description
                    <input
                      maxLength={500}

                      placeholder="Optional server description"

                      value={form.description}

                      onChange={(e) =>
                        setForm({
                          ...form,

                          description: e.target.value,
                        })
                      }
                    />
                  </label>

                  <div className="form-actions">
                    <button
                      type="button"

                      className="button button-secondary"

                      onClick={() => setShowForm(false)}
                    >
                      Cancel
                    </button>

                    <button
                      className="button button-primary"

                      disabled={busyId === "new"}
                    >
                      {busyId === "new" && (
                        <LoaderCircle size={16} className="spin" />
                      )}
                      Register server
                    </button>
                  </div>
                </form>
              </section>
            )}

            <section className="stats-grid">
              <StatCard
                label="Registered servers"

                value={servers.length}

                icon={Database}

                tone="blue"
              />

              <StatCard
                label="Healthy servers"

                value={healthyCount}

                icon={CheckCircle2}

                tone="green"
              />

              <StatCard
                label="Unhealthy servers"

                value={unhealthyCount}

                icon={AlertCircle}

                tone="red"
              />

              <StatCard
                label="Discovered tools"

                value={totalTools}

                icon={ShieldCheck}

                tone="purple"
              />
            </section>

            <section className="panel">
              <div className="section-heading">
                <div>
                  <h2>Connected MCP servers</h2>

                  <p>Health status is based on gateway discovery checks.</p>
                </div>

                <span className="count-pill">{servers.length} total</span>
              </div>

              {loading ? (
                <div className="empty-state">
                  <LoaderCircle className="spin" size={28} />

                  <p>Loading server information...</p>
                </div>
              ) : servers.length === 0 ? (
                <div className="empty-state">
                  <Server size={30} />

                  <h3>No servers registered</h3>

                  <p>Add an MCP server to get started.</p>

                  {user?.role === "admin" && (
                    <button
                      className="button button-primary"
                      onClick={() => setShowForm(true)}
                    >
                      <CirclePlus size={17} />
                      Add your first server
                    </button>
                  )}
                </div>
              ) : (
                <div className="server-list">
                  {servers.map((server) => {
                    const record = healthById[server.id] || {};

                    const serverStatus = !server.enabled
                      ? "disabled"
                      : record.status || "unknown";

                    return (
                      <article
                        className="server-card"

                        key={server.id}
                      >
                        <div className="server-card-top">
                          <div className="server-identity">
                            <div className="server-icon">
                              <Server size={21} />
                            </div>

                            <div>
                              <div className="server-title-row">
                                <h3>{server.name}</h3>

                                <StatusBadge status={serverStatus} />
                              </div>

                              <p className="server-description">
                                {server.description ||
                                  "No description provided"}
                              </p>
                            </div>
                          </div>

                          {user?.role === "admin" && (
                            <div className="server-actions">
                              <button
                                className="button button-secondary button-small"

                                onClick={() =>
                                  performAction(
                                    server,

                                    server.enabled ? "disable" : "enable",
                                  )
                                }

                                disabled={busyId === server.id}
                              >
                                {busyId === server.id ? (
                                  <LoaderCircle
                                    size={15}

                                    className="spin"
                                  />
                                ) : server.enabled ? (
                                  <XCircle size={15} />
                                ) : (
                                  <CheckCircle2 size={15} />
                                )}

                                {server.enabled ? "Disable" : "Enable"}
                              </button>

                              <button
                                className="icon-button delete-button"

                                title="Remove server"

                                aria-label={`Remove ${server.name}`}

                                onClick={() => performAction(server, "delete")}

                                disabled={busyId === server.id}
                              >
                                <Trash2 size={17} />
                              </button>
                            </div>
                          )}
                        </div>

                        <div className="endpoint-row">
                          <span className="endpoint-label">
                            <ExternalLink size={14} />
                            Endpoint
                          </span>

                          <code>{server.url}</code>
                        </div>

                        <div className="server-metrics">
                          <div className="metric">
                            <span className="metric-label">
                              <Activity size={14} />
                              Discovered tools
                            </span>

                            <strong>
                              {record.discovered_tools_count ?? 0}
                            </strong>
                          </div>

                          <div className="metric">
                            <span className="metric-label">
                              <Clock3 size={14} />
                              Last checked
                            </span>

                            <strong className="metric-date">
                              {formatDate(record.last_checked)}
                            </strong>
                          </div>

                          <div className="metric">
                            <span className="metric-label">
                              <CheckCircle2 size={14} />
                              Last successful check
                            </span>

                            <strong className="metric-date">
                              {formatDate(record.last_successful_check)}
                            </strong>
                          </div>
                        </div>

                        {record.last_error && server.enabled && (
                          <div className="server-error">
                            <AlertCircle size={16} />

                            <span>{record.last_error}</span>
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              )}
            </section>
          </>
        )}

        <footer className="page-footer">
          <span>
            <span className="connection-dot" />
            MCP Gateway Management
          </span>

          <span>Registry API · Port 8101</span>
        </footer>
      </main>
    </div>
  );
}

export default App;
