

import { useCallback, useEffect, useState } from "react";


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

  Trash2,

  XCircle,

} from "lucide-react";

import "./App.css";
import AuditLogs from "./AuditLogs";



const API_BASE =
  import.meta.env.VITE_API_BASE || "http://127.0.0.1:8101";

const API_OPTIONS = { credentials: "include" };



function formatDate(value) {

  if (!value) return "Not checked yet";



  const date = new Date(value);

  return Number.isNaN(date.getTime())

    ? value

    : date.toLocaleString();

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

        "Check that the API is running on port 8101."

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
        if (!cancelled) setLoginError("Cannot reach the Registry API. Check that it is running on port 8101.");
      } finally {
        if (!cancelled) setAuthChecking(false);
      }
    }
    restoreSession();
    return () => { cancelled = true; };
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
        body: JSON.stringify({ username: loginUsername.trim(), password: loginPassword }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Login failed. Check your username and password.");
      const meResponse = await fetch(`${API_BASE}/auth/me`, API_OPTIONS);
      if (!meResponse.ok) throw new Error("Login succeeded, but the session could not be verified.");
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
      await fetch(`${API_BASE}/auth/logout`, { method: "POST", ...API_OPTIONS });
    } finally {
      setUser(null);
      setServers([]);
      setHealth([]);
      setShowForm(false);
      setActivePage("overview");
    }
  }


  const healthById = Object.fromEntries(

    health.map((item) => [item.server_id, item])

  );



  const healthyCount = servers.filter(

    (server) =>

      server.enabled &&

      healthById[server.id]?.status === "healthy"

  ).length;



  const unhealthyCount = servers.filter(

    (server) =>

      server.enabled &&

      healthById[server.id]?.status === "unhealthy"

  ).length;



  const totalTools = servers.reduce((total, server) => {

    if (!server.enabled) return total;



    return total + (

      healthById[server.id]?.discovered_tools_count || 0

    );

  }, 0);



  async function performAction(server, action) {

    const labels = {

      enable: "enabled",

      disable: "disabled",

      delete: "removed",

    };



    const confirmed =

      action !== "delete" ||

      window.confirm(

        `Remove "${server.name}" from the registry?`

      );



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
        }

      );



      const result = await response.json();



      if (!response.ok) {

        throw new Error(

          result.detail || "The operation failed."

        );

      }



      setActionMessage(

        `${server.name} ${labels[action]} successfully.`

      );



      await loadDashboard();

    } catch (err) {

      setError(err.message);

    } finally {

      setBusyId("");

    }

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

        throw new Error(

          result.detail || "Could not register the server."

        );

      }



      setForm({ name: "", url: "", description: "" });

      setShowForm(false);

      setActionMessage(

        `${result.server.name} registered successfully.`

      );



      await loadDashboard();

    } catch (err) {

      setError(err.message);

    } finally {

      setBusyId("");

    }

  }



  if (authChecking) {
    return (
      <div className="app-shell" style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
        <main className="main-content" style={{ width: "100%", maxWidth: 440 }}>
          <section className="panel empty-state"><LoaderCircle className="spin" size={28} /><p>Checking your session...</p></section>
        </main>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="app-shell" style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
        <main className="main-content" style={{ width: "100%", maxWidth: 440 }}>
          <section className="panel" style={{ padding: 32 }}>
            <div className="brand" style={{ marginBottom: 24 }}>
              <div className="brand-icon"><Network size={23} /></div>
              <div><h2>MCP Console</h2><span>Sign in to manage your gateway</span></div>
            </div>
            <h1 style={{ marginBottom: 8 }}>Welcome back</h1>
            <p className="page-subtitle" style={{ marginBottom: 24 }}>Use your platform account to continue.</p>
            {loginError && <div className="notice notice-error"><AlertCircle size={18} /><span>{loginError}</span></div>}
            <form className="server-form" onSubmit={handleLogin}>
              <label>Username<input autoComplete="username" required value={loginUsername} onChange={(e) => setLoginUsername(e.target.value)} /></label>
              <label>Password<input type="password" autoComplete="current-password" required value={loginPassword} onChange={(e) => setLoginPassword(e.target.value)} /></label>
              <button className="button button-primary" disabled={loginBusy} style={{ width: "100%", justifyContent: "center" }}>{loginBusy ? <LoaderCircle size={16} className="spin" /> : null}{loginBusy ? "Signing in..." : "Sign in"}</button>
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

        <button type="button" className={`nav-item ${activePage === "overview" ? "active" : ""}`} onClick={() => setActivePage("overview")}><Activity size={18} /><span>Overview</span></button>
        <button type="button" className={`nav-item ${activePage === "servers" ? "active" : ""}`} onClick={() => setActivePage("servers")}><Server size={18} /><span>MCP Servers</span><span className="nav-count">{servers.length}</span></button>
        <button type="button" className={`nav-item ${activePage === "audit" ? "active" : ""}`} onClick={() => setActivePage("audit")}><ShieldCheck size={18} /><span>Audit Logs</span></button>



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

            <div className="breadcrumb">Workspace / {activePage === "audit" ? "Audit Logs" : activePage === "servers" ? "MCP Servers" : "Overview"}</div>
            <h1>{activePage === "audit" ? "Audit Logs" : activePage === "servers" ? "MCP Servers" : "Server Dashboard"}</h1>
            <p className="page-subtitle">{activePage === "audit" ? "Review authenticated tool activity and execution outcomes." : "Monitor and manage your connected MCP servers."}</p>

          </div>



          <div className="topbar-actions">
            <span className="refresh-label">{user.username || user.email || "Signed in"} · {user.role || "member"}</span>
            <button className="button button-secondary" onClick={handleLogout}><LogOut size={16} /> Sign out</button>
            {activePage === "overview" && user?.role === "admin" && <>

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
            </>}

          </div>

        </header>



        {activePage === "audit" ? <AuditLogs /> : <>

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

            <button onClick={() => setActionMessage("")}>

              Dismiss

            </button>

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

              <p>

                Health status is based on gateway discovery checks.

              </p>

            </div>

            <span className="count-pill">

              {servers.length} total

            </span>

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

              {user?.role === "admin" && <button
                className="button button-primary"
                onClick={() => setShowForm(true)}
              >
                <CirclePlus size={17} />
                Add your first server
              </button>}

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



                      {user?.role === "admin" && <div className="server-actions">

                        <button

                          className="button button-secondary button-small"

                          onClick={() =>

                            performAction(

                              server,

                              server.enabled ? "disable" : "enable"

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

                          onClick={() =>

                            performAction(server, "delete")

                          }

                          disabled={busyId === server.id}

                        >

                          <Trash2 size={17} />

                        </button>

                      </div>}

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

                          {formatDate(

                            record.last_successful_check

                          )}

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



         </>}

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
