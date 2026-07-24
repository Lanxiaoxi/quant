import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import ReactEChartsCore from 'echarts-for-react';
import { api } from '@/lib/api';
import type { SimAccount, SimEquity, SimOrder } from '@/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ArrowLeft } from 'lucide-react';

export default function SimDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const { data: acc } = useQuery<SimAccount>({ queryKey: ['sim', id], queryFn: () => api.get(`/sims/${id}`), enabled: !!id });
  const { data: equity } = useQuery<SimEquity[]>({ queryKey: ['sim-equity', id], queryFn: () => api.get(`/sims/${id}/equity`), enabled: !!id });
  const { data: orders } = useQuery<SimOrder[]>({ queryKey: ['sim-orders', id], queryFn: () => api.get(`/sims/${id}/orders?limit=100`), enabled: !!id });
  if (!acc) return <p className="text-muted-foreground">加载中...</p>;

  const eqOpt = equity && equity.length > 1 ? {
    tooltip: { trigger: 'axis' as const },
    xAxis: { type: 'category' as const, data: equity.map((e) => e.date), axisLabel: { rotate: 30, fontSize: 10 } },
    yAxis: { type: 'value' as const },
    series: [
      { name: '总资产', type: 'line', data: equity.map((e) => e.total_value), smooth: true, symbol: 'none',
        lineStyle: { color: '#3b82f6', width: 2 } },
      { name: '现金', type: 'line', data: equity.map((e) => e.cash), smooth: true, symbol: 'none',
        lineStyle: { color: '#94a3b8', width: 1 } },
    ],
    grid: { bottom: 60, top: 10 },
  } : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={() => nav('/sims')}>
          <ArrowLeft className="h-4 w-4 mr-1" /> 返回
        </Button>
        <h2 className="text-xl font-semibold">{acc.name}</h2>
        <Badge variant={acc.status === 'running' ? 'default' : 'secondary'}>{acc.status === 'running' ? '运行中' : '已停止'}</Badge>
      </div>
      <p className="text-sm text-muted-foreground">策略 #{acc.strategy_id} | 初始 ¥{acc.initial_cash.toLocaleString()} | 当前现金 ¥{acc.current_cash.toLocaleString()} | 最后运行 {acc.last_run_date ?? '-'}</p>

      {eqOpt && (
        <Card>
          <CardHeader className="py-2 px-4"><CardTitle className="text-sm">净值走势</CardTitle></CardHeader>
          <CardContent><ReactEChartsCore option={eqOpt} style={{ height: 280 }} notMerge /></CardContent>
        </Card>
      )}

      {equity && (
        <Card>
          <CardHeader className="py-2 px-4"><CardTitle className="text-sm">每日快照</CardTitle></CardHeader>
          <CardContent>
            <Table className="text-xs">
              <TableHeader><TableRow><TableHead>日期</TableHead><TableHead className="text-right">总资产</TableHead><TableHead className="text-right">现金</TableHead><TableHead className="text-right">市值</TableHead></TableRow></TableHeader>
              <TableBody>
                {equity.slice(-10).reverse().map((e, i) => (
                  <TableRow key={i}><TableCell>{e.date}</TableCell><TableCell className="text-right font-mono">¥{e.total_value.toLocaleString()}</TableCell><TableCell className="text-right font-mono">{e.cash.toLocaleString()}</TableCell><TableCell className="text-right font-mono">{e.market_value.toLocaleString()}</TableCell></TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="py-2 px-4"><CardTitle className="text-sm">订单流</CardTitle></CardHeader>
        <CardContent>
          <Table className="text-xs">
            <TableHeader><TableRow><TableHead>标的</TableHead><TableHead>方向</TableHead><TableHead>数量</TableHead><TableHead>信号日</TableHead><TableHead>成交日</TableHead><TableHead>成交价</TableHead><TableHead>金额</TableHead><TableHead>费用</TableHead><TableHead>状态</TableHead><TableHead>原因</TableHead></TableRow></TableHeader>
            <TableBody>
              {orders && orders.length > 0 ? (
                orders.map((o) => (
                <TableRow key={o.id}><TableCell className="font-mono text-xs">{o.symbol}</TableCell>
                  <TableCell style={{ color: o.side === 'buy' ? '#ef4444' : '#22c55e' }}>{o.side === 'buy' ? '买' : '卖'}</TableCell>
                  <TableCell className="font-mono">{o.qty}</TableCell><TableCell>{o.signal_date}</TableCell>
                  <TableCell>{o.fill_date ?? '-'}</TableCell>                  <TableCell className="font-mono">{o.fill_price != null ? o.fill_price.toFixed(2) : '-'}</TableCell>
                  <TableCell className="font-mono">{o.amount > 0 ? '¥' + o.amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-'}</TableCell>
                  <TableCell className="font-mono text-muted-foreground">{o.fee > 0 ? o.fee.toFixed(2) : '-'}</TableCell>
                  <TableCell><Badge variant={o.status === 'filled' ? 'default' : o.status === 'rejected' ? 'destructive' : 'secondary'} className="text-xs">{o.status}</Badge></TableCell>
                  <TableCell className="text-muted-foreground text-xs">{o.reason}</TableCell></TableRow>
                ))
              ) : (
                <TableRow><TableCell colSpan={10} className="text-center text-muted-foreground py-6 text-xs">暂无订单记录</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
