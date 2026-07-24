export interface Strategy {
  id: number;
  name: string;
  code: string;
  description: string;
  default_config: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
}

export interface ParamSchema {
  name: string;
  default: unknown;
  min: number | null;
  max: number | null;
  step: number | null;
  label: string;
}

export interface ValidateResult {
  name: string;
  params: ParamSchema[];
}

export interface BacktestConfig {
  strategy_id: number;
  start: string;
  end: string;
  initial_cash?: number;
  fill_mode?: string;
  slippage_pct?: number;
  commission_rate?: number;
  commission_min?: number;
  stamp_tax_sell?: number;
  benchmark?: string;
  params?: Record<string, unknown>;
}

export interface BacktestRunItem {
  id: number;
  strategy_id: number;
  status: 'pending' | 'running' | 'done' | 'failed';
  config: Record<string, unknown>;
  metrics: Record<string, number> | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface EquityRow {
  date: string;
  total_value: number;
  cash: number;
  market_value: number;
  benchmark_value?: number;
}

export interface Trade {
  symbol: string;
  side: string;
  qty: number;
  signal_date: string;
  fill_date: string;
  fill_price: number;
  amount: number;
  fee: number;
  status: string;
  reason: string;
}

export interface DataStatus {
  table: string;
  rows: number;
  min_date: string | null;
  max_date: string | null;
}

export interface SimAccount {
  id: number;
  name: string;
  strategy_id: number;
  initial_cash: number;
  current_cash: number;
  status: string;
  last_run_date: string | null;
  created_at?: string;
}

export interface SimEquity {
  date: string;
  total_value: number;
  cash: number;
  market_value: number;
}

export interface SimOrder {
  id: number;
  symbol: string;
  side: string;
  qty: number;
  signal_date: string;
  fill_date: string | null;
  fill_price: number | null;
  amount: number;
  fee: number;
  status: string;
  reason: string;
}
