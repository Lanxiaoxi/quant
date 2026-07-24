/**
 * 回测运行状态 — 全局 zustand store。
 * 切出页面回测继续，回来仍可看到运行态。
 */
import { create } from 'zustand';
import { api } from '@/lib/api';

export interface RunningBacktest {
  runId: number;
  strategyId: number;
  strategyName: string;
  start: string;
  end: string;
  startedAt: number; // Date.now()
  status: 'pending' | 'running' | 'done' | 'failed';
  metrics: Record<string, number> | null;
  error: string | null;
}

interface BacktestState {
  running: RunningBacktest | null;

  startBacktest: (config: {
    strategyId: number; strategyName: string;
    start: string; end: string;
    params: Record<string, unknown>;
    initial_cash: number; fill_mode: string;
  }) => Promise<void>;

  pollProgress: () => Promise<void>;
  clearRunning: () => void;
}

export const useBacktestStore = create<BacktestState>((set, get) => ({
  running: null,

  startBacktest: async (config) => {
    const r = await api.post<{ id: number }>('/backtests', {
      strategy_id: config.strategyId,
      start: config.start,
      end: config.end,
      initial_cash: config.initial_cash,
      fill_mode: config.fill_mode,
      slippage_pct: 0.002,
      commission_rate: 0.00025,
      commission_min: 5,
      stamp_tax_sell: 0.0005,
      params: config.params,
    });
    set({
      running: {
        runId: r.id,
        strategyId: config.strategyId,
        strategyName: config.strategyName,
        start: config.start,
        end: config.end,
        startedAt: Date.now(),
        status: 'running',
        metrics: null,
        error: null,
      },
    });
  },

  pollProgress: async () => {
    const running = get().running;
    if (!running) return;

    try {
      const r = await api.get<{
        id: number; status: string; metrics: Record<string, number> | null; error: string | null;
      }>(`/backtests/${running.runId}`);

      set({
        running: {
          ...running,
          status: r.status as RunningBacktest['status'],
          metrics: r.metrics,
          error: r.error,
        },
      });
    } catch {
      set({ running: { ...running, status: 'failed', error: '轮询失败' } });
    }
  },

  clearRunning: () => set({ running: null }),
}));
