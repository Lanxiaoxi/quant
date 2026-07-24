import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Plus, Play, Square, Trash2, TrendingUp, FileText } from 'lucide-react';
import type { Strategy, SimAccount } from '@/types';

export default function SimsList() {
  const { data } = useQuery({ queryKey: ['sims'], queryFn: () => api.get<SimAccount[]>('/sims') });
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [sid, setSid] = useState<number | null>(null);
  const [cash, setCash] = useState(1_000_000);
  const [logAid, setLogAid] = useState<number | null>(null);
  const { data: strategies } = useQuery({
    queryKey: ['strategies'], queryFn: () => api.get<Strategy[]>('/strategies'), enabled: open,
  });

  const create = async () => {
    if (!sid) return;
    await api.post('/sims', { name, strategy_id: sid, initial_cash: cash });
    qc.invalidateQueries({ queryKey: ['sims'] }); setOpen(false);
  };
  const del = async (id: number) => { await api.del(`/sims/${id}`); qc.invalidateQueries({ queryKey: ['sims'] }); };
  const act = async (id: number, action: string) => { await api.post(`/sims/${id}/${action}`); qc.invalidateQueries({ queryKey: ['sims'] }); };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold">模拟交易</h2>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild><Button size="sm"><Plus className="h-4 w-4 mr-1" /> 新建账户</Button></DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>新建模拟账户</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>账户名</Label><Input value={name} onChange={(e) => setName(e.target.value)} /></div>
              <div>
                <Label>策略</Label>
                {strategies && strategies.length > 0 ? (
                  <Select value={sid != null ? String(sid) : ''} onValueChange={(v) => setSid(Number(v))}>
                    <SelectTrigger><SelectValue placeholder="选择策略" /></SelectTrigger>
                    <SelectContent>
                      {strategies.map(s => (
                        <SelectItem key={s.id} value={String(s.id)}>{s.name} (#{s.id})</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <p className="text-xs text-muted-foreground py-1">加载策略列表...</p>
                )}
              </div>
              <div><Label>初始资金</Label><Input type="number" value={cash} onChange={(e) => setCash(Number(e.target.value))} /></div>
              <Button onClick={create} disabled={!name || !sid}>创建</Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        {data?.map((a) => (
          <Card key={a.id} className="cursor-pointer hover:shadow-md" onClick={() => nav(`/sims/${a.id}`)}>
            <CardHeader className="pb-2 flex-row items-start justify-between">
              <div>
                <CardTitle className="text-base">{a.name}</CardTitle>
                <CardDescription className="text-xs">策略 #{a.strategy_id}</CardDescription>
              </div>
              <Badge variant={a.status === 'running' ? 'default' : 'secondary'}>
                <TrendingUp className="h-3 w-3 mr-1" /> {a.status === 'running' ? '运行中' : '已停止'}
              </Badge>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">¥{a.current_cash.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground mt-1">初始 ¥{a.initial_cash.toLocaleString()} / 最后运行 {a.last_run_date ?? '-'}</p>
              <div className="flex gap-1 mt-3" onClick={(e) => e.stopPropagation()}>
                {a.status !== 'running' ? (
                  <Button size="sm" variant="outline" onClick={() => act(a.id, 'start')}>
                    <Play className="h-3 w-3 mr-1" /> 启动</Button>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => act(a.id, 'stop')}>
                    <Square className="h-3 w-3 mr-1" /> 暂停</Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setLogAid(a.id)}>
                  <FileText className="h-3 w-3" />
                </Button>
                <Button size="sm" variant="ghost" onClick={() => del(a.id)}><Trash2 className="h-3 w-3" /></Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 策略日志弹窗 */}
      <Dialog open={logAid != null} onOpenChange={(v) => { if (!v) setLogAid(null); }}>
        <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
          <DialogHeader><DialogTitle>策略日志</DialogTitle></DialogHeader>
          <SimLogs aid={logAid!} />
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SimLogs({ aid }: { aid: number }) {
  const { data: logs, isLoading } = useQuery({
    queryKey: ['sim-logs', aid],
    queryFn: () => api.get<{ date: string; level: string; msg: string }[]>(`/sims/${aid}/logs?limit=10`),
  });
  if (isLoading) return <p className="text-sm text-muted-foreground">加载中...</p>;
  if (!logs || logs.length === 0) return <p className="text-sm text-muted-foreground">暂无策略日志，模拟账户可能尚未运行</p>;
  return (
    <div className="overflow-auto flex-1 -mx-2">
      <table className="w-full text-xs">
        <tbody>
          {logs.map((l, i) => (
            <tr key={i} className="border-b last:border-b-0">
              <td className="py-1 px-2 font-mono text-muted-foreground whitespace-nowrap">{String(l.date).slice(0, 10) ?? l.date}</td>
              <td className="py-1 px-2 w-12">
                <Badge variant={l.level === 'ERROR' ? 'destructive' : l.level === 'WARN' ? 'secondary' : 'outline'} className="text-[10px] px-1 h-4">
                  {l.level}
                </Badge>
              </td>
              <td className="py-1 px-2 font-mono break-all">{l.msg}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
