import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import ReactEChartsCore from 'echarts-for-react';
import { api } from '@/lib/api';
import type { BacktestRunItem, EquityRow, Trade } from '@/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { ArrowLeft, ChevronRight, AlertCircle } from 'lucide-react';

const RED = '#ef4444', GREEN = '#22c55e';
const R = (v: number | null | undefined, d = 4) => v != null ? Number(v).toFixed(d) : '-';

function MetricCard({ label, value, isPct }: { label: string; value: number | null | undefined; isPct?: boolean }) {
  return (
    <Card>
      <CardHeader className="py-2 px-3"><CardTitle className="text-xs font-normal text-muted-foreground">{label}</CardTitle></CardHeader>
      <CardContent className="py-0 px-3 pb-2">
        <p className="text-lg font-semibold" style={{ color: value != null && value >= 0 ? RED : GREEN }}>
          {value != null ? (isPct ? (value * 100).toFixed(2) + '%' : R(value, 2)) : '-'}
        </p>
      </CardContent>
    </Card>
  );
}

function buildChart(equity: EquityRow[]) {
  const dates = equity.map((e) => e.date);
  const tv = equity.map((e) => e.total_value);
  const peak = tv.reduce((a: number[], v, i) => { a.push(Math.max(v, a[i - 1] ?? 0)); return a; }, [] as number[]);
  const dd = tv.map((v, i) => ((v / peak[i] - 1) * 100).toFixed(2));
  const hasBench = equity.some((e) => e.benchmark_value != null);
  return {
    tooltip: { trigger: 'axis' as const },
    legend: { data: ['策略净值', ...(hasBench ? ['基准'] : []), '回撤 %'], top: 0 },
    xAxis: { type: 'category' as const, data: dates, axisLabel: { rotate: 30, fontSize: 10 } },
    yAxis: [
      { type: 'value' as const, name: '净值', axisLabel: { formatter: (v: number) => (v / 10000).toFixed(0) + '万' } },
      { type: 'value' as const, name: '回撤 %', max: 0, axisLabel: { formatter: '{value}%' } },
    ],
    series: [
      { name: '策略净值', type: 'line', data: tv, smooth: true, symbol: 'none',
        lineStyle: { color: '#3b82f6', width: 2 }, itemStyle: { color: '#3b82f6' } },
      ...(hasBench ? [{ name: '基准', type: 'line', data: equity.map((e) => e.benchmark_value ?? 0),
        smooth: true, symbol: 'none', lineStyle: { color: '#94a3b8', type: 'dashed' as const, width: 1.5 } }] : []),
      { name: '回撤 %', type: 'line', yAxisIndex: 1, data: dd, symbol: 'none',
        areaStyle: { color: 'rgba(239,68,68,0.08)' }, lineStyle: { color: '#fca5a5', width: 1 } },
    ],
    grid: { bottom: 60, top: 30 },
  };
}

function monthlyTable(equity: EquityRow[]) {
  const mMap = equity.reduce((acc, e) => { acc.set(e.date.substring(0, 7), e.total_value); return acc; }, new Map<string, number>());
  const entries = [...mMap.entries()].sort();
  const table = new Map<number, Record<number, number>>();
  for (let i = 0; i < entries.length; i++) {
    const [k, v] = entries[i];
    const y = Number(k.slice(0, 4)), m = Number(k.slice(5));
    if (!table.has(y)) table.set(y, {});
    const prev = i > 0 ? entries[i - 1][1] : equity[0].total_value;
    table.get(y)![m] = v / prev - 1;
  }
  const years = [...table.keys()].sort();
  const allMonths = new Set<number>();
  table.forEach((mRec) => Object.keys(mRec).forEach((k) => allMonths.add(Number(k))));
  const sortedMonths = [...allMonths].sort((a, b) => a - b);
  return (
    <Table className="text-xs">
      <TableHeader>
        <TableRow>
          <TableHead className="w-16">年份</TableHead>
          {sortedMonths.map((m) => <TableHead key={m} className="text-center w-10">{m}月</TableHead>)}
        </TableRow>
      </TableHeader>
      <TableBody>
        {years.map((y) => (
          <TableRow key={y}>
            <TableCell className="font-medium">{y}</TableCell>
            {sortedMonths.map((m) => {
              const v = table.get(y)?.[m];
              return (
                <TableCell key={m} className="text-center p-1"
                  style={{ backgroundColor: v != null ? (v >= 0 ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)') : undefined }}>
                  {v != null ? (v * 100).toFixed(1) + '%' : '-'}
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function BacktestReport() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const { data: run } = useQuery({
    queryKey: ['backtest', id], queryFn: () => api.get<BacktestRunItem>(`/backtests/${id}`),
    enabled: !!id,
  });
  const { data: series, isLoading: seriesLoading } = useQuery({
    queryKey: ['backtest-series', id], queryFn: () => api.get<EquityRow[]>(`/backtests/${id}/series`),
    enabled: !!id && run?.status === 'done',
  });
  const { data: trades, isLoading: tradesLoading } = useQuery({
    queryKey: ['backtest-trades', id], queryFn: () => api.get<Trade[]>(`/backtests/${id}/trades`),
    enabled: !!id && run?.status === 'done',
  });

  if (!run) return <p className="text-muted-foreground">加载中...</p>;
  if (run.status === 'failed') {
    const errLines = (run.error || '未知错误').split('\n');
    const errSummary = errLines[0];
    const errTraceback = errLines.slice(1).join('\n');
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => nav('/strategies')}>
            <ArrowLeft className="h-4 w-4 mr-1" /> 返回
          </Button>
          <h2 className="text-xl font-semibold">回测报告 #{id}</h2>
        </div>
        <Card>
          <CardHeader className="py-2 px-4"><CardTitle className="text-sm text-destructive">回测失败</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-start gap-2 text-sm bg-destructive/5 rounded-md p-3">
              <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5 text-destructive" />
              <span className="font-mono whitespace-pre-wrap break-all">{errSummary}</span>
            </div>
            {errTraceback && (
              <details>
                <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">展开错误堆栈</summary>
                <pre className="mt-2 text-xs font-mono bg-muted rounded-md p-3 overflow-auto max-h-96 whitespace-pre-wrap break-all">{errTraceback}</pre>
              </details>
            )}
            <Button variant="outline" size="sm" onClick={() => nav(`/strategies/${run.strategy_id}`)}>
              返回编辑策略
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }
  if (run.status !== 'done') return <p className="text-muted-foreground">回测进行中 (ID: {id})...</p>;
  if (seriesLoading || tradesLoading) return <div className="flex items-center gap-2 text-muted-foreground"><span className="inline-block w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />加载报告数据...</div>;

  const m = run.metrics ?? {};
  const cfgStart = (run.config as any)?.start?.toString().slice(0, 10) || '';
  const cfgEnd = (run.config as any)?.end?.toString().slice(0, 10) || '';
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => nav('/strategies')}>
          <ArrowLeft className="h-4 w-4 mr-1" /> 返回
        </Button>
        <h2 className="text-xl font-semibold">回测报告 #{id}</h2>
        <span className="text-sm text-muted-foreground">
          回测区间 {cfgStart} ~ {cfgEnd}
          {run.created_at && <span className="ml-3 text-xs">运行于 {new Date(run.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>}
        </span>
        <div className="flex-1" />
        <Button variant="ghost" size="sm" onClick={() => nav(`/strategies/${run.strategy_id}`)}>
          编辑策略 <ChevronRight className="h-3.5 w-3.5 ml-1" />
        </Button>
      </div>
      <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
        <MetricCard label="总收益" value={m.total_return as number} isPct />
        <MetricCard label="年化收益" value={m.annual_return as number} isPct />
        <MetricCard label="最大回撤" value={m.max_drawdown as number} isPct />
        <MetricCard label="夏普" value={m.sharpe as number} />
        <MetricCard label="卡玛" value={m.calmar as number} />
        <MetricCard label="基准收益" value={m.benchmark_return as number} isPct />
      </div>
      <Card>
        <CardHeader className="py-2 px-4"><CardTitle className="text-sm">净值与回撤</CardTitle></CardHeader>
        <CardContent>
          {series && <ReactEChartsCore option={buildChart(series)} style={{ height: 360 }} notMerge />}
        </CardContent>
      </Card>
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader className="py-2 px-4"><CardTitle className="text-sm">月度收益</CardTitle></CardHeader>
          <CardContent>{series && monthlyTable(series)}</CardContent>
        </Card>
        <Card>
          <CardHeader className="py-2 px-4"><CardTitle className="text-sm">成交明细</CardTitle></CardHeader>
          <CardContent>
            <Table className="text-xs">
              <TableHeader><TableRow>
                <TableHead>标的</TableHead><TableHead>方向</TableHead><TableHead>数量</TableHead>
                <TableHead>成交价</TableHead><TableHead>金额</TableHead><TableHead>费用</TableHead><TableHead>日期</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {trades?.slice(-20).reverse().map((t, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-mono text-xs">{t.symbol}</TableCell>
                    <TableCell style={{ color: t.side === 'buy' ? RED : GREEN }}>{t.side === 'buy' ? '买' : '卖'}</TableCell>
                    <TableCell>{t.qty}</TableCell>
                    <TableCell className="font-mono">{R(t.fill_price, 2)}</TableCell>
                    <TableCell className="font-mono">{R(t.amount, 2)}</TableCell>
                    <TableCell className="font-mono text-muted-foreground">{R(t.fee, 2)}</TableCell>
                    <TableCell className="text-muted-foreground">{t.fill_date}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
