import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Auth from './pages/Auth';
import Dashboard from './pages/Dashboard';
import Scanner from './pages/Scanner';
import Analysis from './pages/Analysis';
import TradingControls from './pages/TradingControls';
import Positions from './pages/Positions';
import TradeHistory from './pages/TradeHistory';
import Performance from './pages/Performance';
import Missions from './pages/Missions';
import Exchanges from './pages/Exchanges';
import Settings from './pages/Settings';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth" element={<Auth />} />
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/scanner" element={<Scanner />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/trading" element={<TradingControls />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/history" element={<TradeHistory />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/missions" element={<Missions />} />
          <Route path="/exchanges" element={<Exchanges />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
