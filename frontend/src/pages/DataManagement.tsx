import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { DataStatus } from '@/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { RefreshCw } from 'lucide-react';

const TABLE_NOTE: Record<string, string> = {
  trade_cal: '交易日历',
  daily: 'A股股票日线行情（OHLCV）',
  adj_factor: '复权因子',
  daily_basic: '每日基础指标（市值、PE、PB等）',
  fund_daily: '场内ETF/LOF日线行情',
  fund_nav: '场外公募基金净值',
  index_daily: '指数日线行情',
  sync_log: '数据同步日志',
};

export default function DataManagement() {
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['data-status'],
    queryFn: () => api.get<DataStatus[]>('/data/status'),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold">数据管理</h2>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? 'animate-spin' : ''}`} /> 刷新
        </Button>
      </div>
      <Card>
        <CardHeader className="py-2 px-4"><CardTitle className="text-sm">行情表覆盖范围</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? <p className="text-muted-foreground">加载中...</p> : (
            <Table className="text-sm">
              <TableHeader>
                <TableRow>
                  <TableHead>表名</TableHead>
                  <TableHead>备注</TableHead>
                  <TableHead className="text-right">行数</TableHead>
                  <TableHead>最早日期</TableHead>
                  <TableHead>最近日期</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.map((r) => (
                  <TableRow key={r.table}>
                    <TableCell className="font-mono">{r.table}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{TABLE_NOTE[r.table] ?? '-'}</TableCell>
                    <TableCell className="text-right">{r.rows.toLocaleString()}</TableCell>
                    <TableCell>{r.min_date ?? '-'}</TableCell>
                    <TableCell>{r.max_date ?? '-'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
