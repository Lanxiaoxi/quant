import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Strategy, BacktestRunItem } from '@/types';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';
import { Plus, Edit, Trash2, MoreHorizontal, History } from 'lucide-react';

const RED = '#ef4444', GREEN = '#22c55e';

/** 单个策略的回测列表获取 */
function StrategyRow({ s, onDelete }: { s: Strategy; onDelete: (id: number) => void }) {
  const nav = useNavigate();
  const { data: runs } = useQuery({
    queryKey: ['backtests', s.id],
    queryFn: () => api.get<BacktestRunItem[]>(`/backtests?strategy_id=${s.id}&limit=10`),
    staleTime: 30_000,
  });

  return (
    <TableRow>
      <TableCell className="font-medium">
        <button onClick={() => nav(`/strategies/${s.id}`)}
          className="hover:text-primary hover:underline text-left">
          {s.name}
        </button>
      </TableCell>
      <TableCell className="text-muted-foreground">{runs ? runs.length : 0} 次</TableCell>
      <TableCell className="text-muted-foreground text-sm">
        {s.updated_at ? new Date(s.updated_at).toLocaleDateString('zh-CN') : '-'}
      </TableCell>
      <TableCell className="w-[220px]">
        <div className="flex items-center gap-1.5">
          {/* 最近回测快捷入口 */}
          {runs && runs.slice(0, 3).filter(r => r.status === 'done').map(r => (
            <Badge key={r.id} variant="outline" className="cursor-pointer hover:bg-secondary text-[10px] px-1.5 h-5"
              onClick={() => nav(`/backtests/${r.id}`)}>
              {((Number(r.metrics?.total_return) || 0) * 100).toFixed(1)}%
            </Badge>
          ))}
          {/* 更多菜单 */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8"><MoreHorizontal className="h-4 w-4" /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">{s.name}</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => nav(`/strategies/${s.id}`)}>
                <Edit className="h-3.5 w-3.5 mr-2" /> 编辑策略
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuLabel className="text-[10px] font-normal text-muted-foreground">回测报告</DropdownMenuLabel>
              {runs && runs.filter(r => r.status === 'done').length === 0 && (
                <div className="px-2 py-2 text-xs text-muted-foreground">暂无回测记录</div>
              )}
              {runs && runs.filter(r => r.status === 'done').slice(0, 10).map(r => {
                const ret = Number(r.metrics?.total_return) || 0;
                const time = r.created_at ? new Date(r.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '?';
                return (
                  <DropdownMenuItem key={r.id} onClick={() => nav(`/backtests/${r.id}`)}
                    className="flex items-center justify-between gap-4">
                    <span className="text-xs font-mono text-muted-foreground">{time}</span>
                    <span className="text-xs font-mono font-medium" style={{ color: ret >= 0 ? RED : GREEN }}>
                      {(ret * 100).toFixed(1)}%
                    </span>
                  </DropdownMenuItem>
                );
              })}
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive" onClick={() => onDelete(s.id)}>
                <Trash2 className="h-3.5 w-3.5 mr-2" /> 删除策略
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </TableCell>
    </TableRow>
  );
}

export default function StrategiesList() {
  const { data, isLoading } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => api.get<Strategy[]>('/strategies'),
  });
  const qc = useQueryClient();
  const nav = useNavigate();

  const del = async (id: number) => {
    await api.del(`/strategies/${id}`);
    qc.invalidateQueries({ queryKey: ['strategies'] });
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-semibold">策略列表</h2>
        <Button size="sm" onClick={() => nav('/strategies/new')}>
          <Plus className="h-4 w-4 mr-1" /> 新建
        </Button>
      </div>
      {isLoading ? <p className="text-muted-foreground">加载中...</p> : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>名称</TableHead>
              <TableHead>回测次数</TableHead>
              <TableHead>最近更新</TableHead>
              <TableHead className="w-[220px]">操作 / 回测报告</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((s) => (
              <StrategyRow key={s.id} s={s} onDelete={del} />
            ))}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground py-12">
                  暂无策略，点击"新建"开始
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
