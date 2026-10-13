
import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";
import "./AuditLogs.css";

const API_BASE =
  import.meta.env.VITE_API_BASE || "http://127.0.0.1:8101";

const PAGE_SIZE = 25;

function formatTimestamp(value) {
  if (!value) return "—";

  const date = new Date(value);

  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString();
}

function OutcomeBadge({ outcome }) {
  const Icon =
    outcome === "success"
      ? CheckCircle2
      : outcome === "error"
        ? AlertCircle
        : ShieldAlert;

  return (
    <span className={`audit-outcome audit-outcome-${outcome}`}>
      <Icon size={14} />
      {outcome}
    </span>
  );
}

export default function AuditLogs() {
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);

  const [outcome, setOutcome] = useState("");
  const [username, setUsername] = useState("");
  const [serverName, setServerName] = useState("");

  const [appliedFilters, setAppliedFilters] = useState({
    outcome: "",
    username: "",
    serverName: "",
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    setError("");

    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });

    if (appliedFilters.outcome) {
      params.set("outcome", appliedFilters.outcome);
    }

    if (appliedFilters.username.trim()) {
      params.set("username", appliedFilters.username.trim());
    }

    if (appliedFilters.serverName.trim()) {
      params.set("server_name", appliedFilters.serverName.trim());
    }

    try {
      const response = await fetch(
        `${API_BASE}/audit-logs?${params.toString()}`,
        {
          method: "GET",
          credentials: "include",
        }
      );

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error(
            "Your session has expired. Please sign in again."
          );
        }

        if (response.status === 403) {
          throw new Error(
            "Audit logs are available to administrators only."
          );
        }

        throw new Error(
          data.detail || "Could not load audit logs."
        );
      }

      setLogs(data.logs || []);
      setTotal(data.total || 0);
    } catch (err) {
      setLogs([]);
      setTotal(0);
      setError(
        err.message ||
          "Could not load audit logs. Check the Registry API connection."
      );
    } finally {
      setLoading(false);
    }
  }, [offset, appliedFilters, refreshKey]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  function applyFilters(event) {
    event.preventDefault();

    setOffset(0);
    setAppliedFilters({
      outcome,
      username,
      serverName,
    });
  }

  return (
    <section className="panel audit-panel">
      <div className="section-heading">
        <div>
          <h2>Audit logs</h2>
          <p>
            Review tool-call outcomes, execution times, and recorded errors.
          </p>
        </div>

        <button
          type="button"
          className="button button-secondary"
          onClick={() => setRefreshKey((value) => value + 1)}
          disabled={loading}
        >
          <RefreshCw
            size={15}
            className={loading ? "spin" : ""}
          />
          Refresh
        </button>
      </div>

      <form className="audit-filters" onSubmit={applyFilters}>
        <label>
          Outcome
          <select
            value={outcome}
            onChange={(event) => setOutcome(event.target.value)}
          >
            <option value="">All outcomes</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
            <option value="denied">Denied</option>
          </select>
        </label>

        <label>
          Username
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="Filter by user"
            maxLength={80}
          />
        </label>

        <label>
          MCP server
          <input
            value={serverName}
            onChange={(event) => setServerName(event.target.value)}
            placeholder="Filter by server"
            maxLength={80}
          />
        </label>

        <button
          className="button button-primary"
          type="submit"
        >
          <Search size={15} />
          Apply filters
        </button>
      </form>

      {error && (
        <div className="notice notice-error">
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      <div className="audit-summary">
        <span>
          {total.toLocaleString()} event{total === 1 ? "" : "s"}
        </span>

        <span>
          Showing{" "}
          {total === 0 ? 0 : offset + 1}
          {"–"}
          {Math.min(offset + logs.length, total)}
        </span>
      </div>

      {loading ? (
        <div className="empty-state">
          <RefreshCw className="spin" size={26} />
          <p>Loading audit events…</p>
        </div>
      ) : !error && logs.length === 0 ? (
        <div className="empty-state">
          <ShieldAlert size={28} />
          <h3>No audit events found</h3>
          <p>
            Try changing the filters or execute a tool through the gateway.
          </p>
        </div>
      ) : (
        !error && (
          <div className="audit-table-wrap">
            <table className="audit-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>User</th>
                  <th>Server / tool</th>
                  <th>Duration</th>
                  <th>Outcome</th>
                  <th>Details</th>
                </tr>
              </thead>

              <tbody>
                {logs.map((log) => (
                  <tr key={log.id}>
                    <td className="audit-time">
                      {formatTimestamp(log.timestamp)}
                    </td>

                    <td>{log.username || "Unknown"}</td>

                    <td>
                      <strong>{log.server_name || "—"}</strong>
                      <span className="audit-tool">
                        {log.tool_name || "—"}
                      </span>
                    </td>

                    <td>
                      {log.duration_ms == null
                        ? "—"
                        : `${log.duration_ms} ms`}
                    </td>

                    <td>
                      <OutcomeBadge outcome={log.outcome} />
                    </td>

                    <td
                      className="audit-details"
                      title={log.details || ""}
                    >
                      {log.details || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      <div className="audit-pagination">
        <button
          type="button"
          className="button button-secondary"
          disabled={loading || offset === 0}
          onClick={() =>
            setOffset((value) => Math.max(0, value - PAGE_SIZE))
          }
        >
          Previous
        </button>

        <span>
          Page {Math.floor(offset / PAGE_SIZE) + 1} of{" "}
          {Math.max(1, Math.ceil(total / PAGE_SIZE))}
        </span>

        <button
          type="button"
          className="button button-secondary"
          disabled={loading || offset + PAGE_SIZE >= total}
          onClick={() => setOffset((value) => value + PAGE_SIZE)}
        >
          Next
        </button>
      </div>
    </section>
  );
}
