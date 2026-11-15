import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Auth from './pages/Auth';
import Dashboard from './pages/Dashboard';
import Scanner from './pages/Scanner';
import Analysis from './pages/Analysis';
import Trading from './pages/Trading';
import Positions from './pages/Positions';
import History from './pages/History';
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
          <Route path="/trading" element={<Trading />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/history" element={<History />} />
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
