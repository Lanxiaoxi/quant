import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Login from '@/pages/Login';
import Layout from '@/pages/Layout';
import StrategiesList from '@/pages/StrategiesList';
import StrategyEditor from '@/pages/StrategyEditor';
import BacktestReport from '@/pages/BacktestReport';
import DataManagement from '@/pages/DataManagement';
import SimsList from '@/pages/SimsList';
import SimDetail from '@/pages/SimDetail';
import DocsPage from '@/pages/DocsPage';

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 10_000 } } });

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<Layout />}>
            <Route path="/strategies" element={<StrategiesList />} />
            <Route path="/strategies/:id" element={<StrategyEditor />} />
            <Route path="/backtests/:id" element={<BacktestReport />} />
            <Route path="/sims" element={<SimsList />} />
            <Route path="/sims/:id" element={<SimDetail />} />
            <Route path="/data" element={<DataManagement />} />
            <Route path="/docs" element={<DocsPage />} />
            <Route path="*" element={<Navigate to="/strategies" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
