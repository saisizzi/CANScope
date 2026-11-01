import { useEffect, useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

type Frame = {
  timestamp: string;
  can_id: number;
  sender: string;
  dlc: number;
  payload_hex: string;
  decoded: Record<string, number | string>;
};

type Anomaly = {
  timestamp: string;
  severity: string;
  source: string;
  kind: string;
  can_id: number;
  message: string;
  details: Record<string, unknown>;
};

type DashboardData = {
  stats: {
    total_frames: number;
    active_ecus: number;
    messages_per_second: number;
    bus_utilization: number;
    last_update: string;
  };
  ecus: Array<{ ecu_id: string; name: string; can_id: number; enabled: boolean; interval_ms: number }>;
  latest_messages: Frame[];
  anomalies: Anomaly[];
  signals: Record<string, Record<string, { latest: number; average: number; min: number; max: number }>>;
};

const apiBase = 'http://localhost:8000';

const buildChartData = (frames: Frame[]) =>
  frames.map((frame, index) => ({
    index,
    rpm: frame.decoded.rpm ?? 0,
    speed: frame.decoded.vehicle_speed ?? 0,
    voltage: frame.decoded.battery_voltage ?? 0,
    temp: frame.decoded.coolant_temp ?? 0,
  }));

function App() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadInitial = async () => {
      try {
        const response = await fetch(`${apiBase}/api/dashboard`);
        const data = await response.json();
        setDashboard(data);
      } catch (error) {
        console.error('Dashboard load failed', error);
      } finally {
        setLoading(false);
      }
    };

    loadInitial();
    const socket = new WebSocket('ws://localhost:8000/ws/traffic');
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data) as DashboardData;
      setDashboard(data);
    };

    return () => socket.close();
  }, []);

  const chartData = useMemo(() => (dashboard ? buildChartData(dashboard.latest_messages) : []), [dashboard]);

  if (loading || !dashboard) {
    return <div className="app-shell">Loading CANScope diagnostics…</div>;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AUTOMOTIVE NETWORK INTELLIGENCE</p>
          <h1>CANScope</h1>
        </div>
        <div className="status-pill">Live simulation active</div>
      </header>

      <section className="metrics-grid">
        <div className="metric-card">
          <span className="label">Total frames</span>
          <strong>{dashboard.stats.total_frames}</strong>
        </div>
        <div className="metric-card">
          <span className="label">Active ECUs</span>
          <strong>{dashboard.stats.active_ecus}</strong>
        </div>
        <div className="metric-card">
          <span className="label">Messages/sec</span>
          <strong>{dashboard.stats.messages_per_second}</strong>
        </div>
        <div className="metric-card warning">
          <span className="label">Bus utilization</span>
          <strong>{dashboard.stats.bus_utilization}%</strong>
        </div>
      </section>

      <section className="panel-grid">
        <div className="panel large-panel">
          <div className="panel-header">
            <h2>Signal trends</h2>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="rpmFill" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#7dd3fc" stopOpacity={0.9} />
                  <stop offset="100%" stopColor="#7dd3fc" stopOpacity={0.1} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#243b53" strokeDasharray="5 5" />
              <XAxis dataKey="index" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" />
              <Tooltip />
              <Legend />
              <Area type="monotone" dataKey="rpm" stroke="#7dd3fc" fill="url(#rpmFill)" name="RPM" />
              <Line type="monotone" dataKey="speed" stroke="#a78bfa" name="Speed" />
              <Line type="monotone" dataKey="voltage" stroke="#34d399" name="Voltage" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2>ECU status</h2>
          </div>
          <div className="status-list">
            {dashboard.ecus.map((ecu) => (
              <div key={ecu.ecu_id} className="status-item">
                <div>
                  <span className="status-name">{ecu.name}</span>
                  <small>0x{ecu.can_id.toString(16).toUpperCase()}</small>
                </div>
                <span className={`toggle ${ecu.enabled ? 'on' : 'off'}`}>
                  {ecu.enabled ? 'Active' : 'Offline'}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="panel-grid lower-grid">
        <div className="panel">
          <div className="panel-header">
            <h2>Recent CAN frames</h2>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>ID</th>
                  <th>Sender</th>
                  <th>Payload</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.latest_messages.slice(-8).reverse().map((frame) => (
                  <tr key={`${frame.sender}-${frame.timestamp}`}>
                    <td>{new Date(frame.timestamp).toLocaleTimeString()}</td>
                    <td>0x{frame.can_id.toString(16).toUpperCase()}</td>
                    <td>{frame.sender}</td>
                    <td>{frame.payload_hex}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2>Diagnostic events</h2>
          </div>
          <div className="event-list">
            {dashboard.anomalies.length === 0 ? (
              <div className="empty-state">No active anomalies detected</div>
            ) : (
              dashboard.anomalies.slice().reverse().map((anomaly, idx) => (
                <div key={`${anomaly.message}-${idx}`} className={`event-card ${anomaly.severity}`}>
                  <strong>{anomaly.source}</strong>
                  <span>{anomaly.message}</span>
                  <small>{new Date(anomaly.timestamp).toLocaleTimeString()}</small>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Signal analysis</h2>
        </div>
        <div className="signal-grid">
          {Object.entries(dashboard.signals).map(([sender, values]) => (
            <div key={sender} className="signal-block">
              <h3>{sender}</h3>
              {Object.entries(values).map(([name, metrics]) => (
                <div key={name} className="signal-row">
                  <span>{name}</span>
                  <div className="signal-metrics">
                    <strong>{metrics.latest}</strong>
                    <small>{metrics.average} avg</small>
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default App;
