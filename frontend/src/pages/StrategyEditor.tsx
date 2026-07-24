import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Editor from '@monaco-editor/react';
import { api } from '@/lib/api';
import type { Strategy, ValidateResult, BacktestRunItem } from '@/types';
import { useBacktestStore } from '@/stores/backtest';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import {
  Save, Play, RefreshCw, Loader2, ChevronRight, AlertCircle, CheckCircle2,
  Code2, Wrench, History, Terminal, ArrowLeft,
} from 'lucide-react';

/* ---- 模板 ---- */
const DEFAULT_CODE = `from app.engine.strategy import Param, Strategy

class MyStrategy(Strategy):
    param1 = Param(default=10, min=1, max=100, label="参数")

    def setup(self, ctx):
        ctx.universe = ['510300.SH']
        ctx.benchmark = "000300.SH"

    def on_bar(self, ctx):
        close = ctx.history("510300.SH", "close", 5)
        if len(close) < 5:
            return
        ma5 = close.mean()
        ctx.order_target_percent("510300.SH", 0.5)
`;

/* ---- 参数输入控件 ---- */
function ParamField({ p, value, onChange }: { p: { name: string; default: unknown; min?: number | null; max?: number | null; step?: number | null; label: string }; value: unknown; onChange: (v: unknown) => void }) {
  if (typeof p.default === 'number') {
    return (
      <div className="space-y-1">
        <Label className="text-xs">{p.label || p.name}</Label>
        <Input type="number" value={String(value ?? p.default)} min={p.min ?? undefined} max={p.max ?? undefined}
          step={p.step ?? undefined} className="h-8 text-sm"
          onChange={(e) => onChange(e.target.value === '' ? p.default : Number(e.target.value))} />
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <Label className="text-xs">{p.label || p.name}</Label>
      <Input value={String(value ?? p.default)} className="h-8 text-sm"
        onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

/* ---- 运行耗时显示 ---- */
function Elapsed({ start }: { start: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const s = Math.floor((now - start) / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return <>{m > 0 ? `${m}分` : ''}{sec}秒</>;
}

/* ---- 主组件 ---- */
export default function StrategyEditor() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const isNew = id === 'new';
  const nav = useNavigate();
  const qc = useQueryClient();

  // 策略数据（编辑模式）
  const { data: s, isLoading: loading } = useQuery({
    queryKey: ['strategy', id],
    queryFn: () => api.get<Strategy>(`/strategies/${id}`),
    enabled: !isNew,
  });

  const [code, setCode] = useState(isNew ? DEFAULT_CODE : '');
  const [name, setName] = useState('');
  const strategyId = !isNew ? Number(id) : null;

  useEffect(() => { if (s) { setCode(s.code); setName(s.name); } }, [s]);

  // 新建时从 query string 读取 name
  useEffect(() => {
    if (isNew && searchParams.has('name')) {
      setName(searchParams.get('name') || '');
    }
  }, [isNew, searchParams]);

  // 发起回测时的本地错误（如服务端拒绝、网络异常）
  const [launchError, setLaunchError] = useState('');
  // 失败详情展开
  const [showErr, setShowErr] = useState(false);

  // ---- 校验 ----
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<ValidateResult | null>(null);
  const [validateError, setValidateError] = useState('');
  const [params, setParams] = useState<Record<string, unknown>>({});

  const doValidate = async () => {
    if (!strategyId) { setValidateError('请先保存策略'); return; }
    setValidating(true);
    setValidateError('');
    setValidation(null);
    try {
      const v = await api.post<ValidateResult>(`/strategies/${strategyId}/validate`);
      setValidation(v);
      const init: Record<string, unknown> = {};
      v.params.forEach((p) => { init[p.name] = p.default; });
      setParams(init);
    } catch (e: any) {
      setValidateError(e.message ?? '校验失败');
    }
    setValidating(false);
  };

  // ---- 保存 ----
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      if (isNew) {
        const r = await api.post<Strategy>('/strategies', { name: name.trim(), code });
        qc.invalidateQueries({ queryKey: ['strategies'] });
        nav(`/strategies/${r.id}`, { replace: true });
      } else {
        await api.put(`/strategies/${id}`, { name: name.trim(), code });
        qc.invalidateQueries({ queryKey: ['strategies'] });
      }
    } catch (e: any) {
      setValidateError(e.message ?? '保存失败');
    }
    setSaving(false);
  };

  // ---- 回测配置 ----
  const [start, setStart] = useState('2024-01-01');
  const [end, setEnd] = useState('2026-07-01');
  const [cash, setCash] = useState(1_000_000);
  const [fillMode, setFillMode] = useState('next_open');

  // ---- 回测运行（全局 store） ----
  const { running, startBacktest, pollProgress, clearRunning } = useBacktestStore();
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  // 启动轮询
  useEffect(() => {
    if (running && running.status === 'running') {
      pollRef.current = setInterval(pollProgress, 1500);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running?.runId]);

  const run = async () => {
    if (!strategyId) { setValidateError('请先保存策略'); return; }
    await startBacktest({
      strategyId,
      strategyName: name || '未命名',
      start, end,
      initial_cash: cash,
      fill_mode: fillMode,
      params: params as Record<string, unknown>,
    });
  };

  // ---- 回测历史 ----
  const { data: history } = useQuery({
    queryKey: ['backtests', strategyId],
    queryFn: () => api.get<BacktestRunItem[]>(`/backtests?strategy_id=${strategyId}&limit=20`),
    enabled: !!strategyId,
  });

  // ---- tab 状态 ----
  type Tab = 'code' | 'debug';
  const [tab, setTab] = useState<Tab>('code');

  if (loading) return <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />加载策略...</div>;

  return (
    <div className="flex gap-4 h-full">
      {/* ===== 左侧：编辑器 + 调试面板 ===== */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 头部 */}
        <div className="flex items-center gap-3 mb-2 px-1 flex-shrink-0">
          <Button variant="ghost" size="sm" onClick={() => nav('/strategies')} title="返回策略列表">
            <ArrowLeft className="h-4 w-4 mr-1" /> 返回
          </Button>
          <Input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="策略名称" className="h-8 text-sm font-medium w-48" />
          <Button size="sm" onClick={save} disabled={saving}>
            <Save className="h-3.5 w-3.5 mr-1" /> {saving ? '保存中...' : (isNew ? '创建' : '保存')}
          </Button>

          <div className="w-px h-5 bg-border mx-1" />

          <Button size="sm" variant="outline" onClick={doValidate} disabled={validating}>
            <RefreshCw className={`h-3.5 w-3.5 mr-1 ${validating ? 'animate-spin' : ''}`} /> 校验
          </Button>

          <div className="flex-1" />

          {/* tab 切换 */}
          <div className="flex rounded-md border bg-muted/50 p-0.5">
            {([
              { id: 'code' as Tab, icon: Code2, label: '代码' },
              { id: 'debug' as Tab, icon: Terminal, label: '调试' },
            ]).map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={['flex items-center gap-1.5 px-3 py-1 text-xs rounded-sm transition-colors',
                  tab === t.id ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'].join(' ')}>
                <t.icon className="h-3.5 w-3.5" /> {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* 运行状态条 */}
        {running && (
          <div className="px-1 mb-2 flex-shrink-0">
            <div className={[
              'flex items-center gap-3 text-xs border rounded-md px-3 py-2',
              running.status === 'done' ? 'bg-green-50 border-green-200' :
              running.status === 'failed' ? 'bg-destructive/10 border-destructive/30' :
              'bg-primary/5 border-primary/20',
            ].join(' ')}>
              {running.status === 'running' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
              ) : running.status === 'done' ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
              ) : (
                <AlertCircle className="h-3.5 w-3.5 text-destructive" />
              )}
              <span className="text-muted-foreground">
                回测 #{running.runId} · {running.strategyName} · {running.start} ~ {running.end}
              </span>
              {running.status === 'running' && (
                <span className="text-muted-foreground font-mono tabular-nums">
                  <Elapsed start={running.startedAt} />
                </span>
              )}
              {running.status === 'done' && (
                <span className="text-green-700 font-medium">完成</span>
              )}
              {running.status === 'failed' && (
                <span className="text-destructive font-medium cursor-pointer hover:underline" onClick={() => { nav(`/backtests/${running.runId}`); clearRunning(); }}>
                  失败 — {(() => { const lines = (running.error || '未知错误').split('\n'); return lines[0].length > 60 ? lines[0].slice(0, 60) + '...' : lines[0]; })()}（点击查看详情）
                </span>
              )}
            </div>
          </div>
        )}

        {/* 编辑器 / 调试面板 */}
        {tab === 'code' ? (
          <div className="flex-1 min-h-0 border rounded-md overflow-hidden">
            <Editor height="100%" language="python" theme="vs" value={code}
              onChange={(v) => setCode(v ?? '')}
              options={{ minimap: { enabled: false }, fontSize: 13, wordWrap: 'on', scrollBeyondLastLine: false }} />
          </div>
        ) : (
          <div className="flex-1 border rounded-md p-4 space-y-3 overflow-auto">
            <h3 className="text-sm font-semibold flex items-center gap-2"><Terminal className="h-4 w-4" /> 语法检查与调试</h3>

            {validateError ? (
              <div className="flex items-start gap-2 text-xs text-destructive bg-destructive/10 rounded-md p-3">
                <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                <pre className="whitespace-pre-wrap font-mono">{validateError}</pre>
              </div>
            ) : validation ? (
              <div className="flex items-center gap-2 text-xs text-green-700 bg-green-50 rounded-md p-3">
                <CheckCircle2 className="h-4 w-4" />
                <span>语法检查通过 · 类名: <Badge variant="outline" className="ml-1 text-xs">{validation.name}</Badge> · 参数: {validation.params.length} 个</span>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">点击 <Badge variant="secondary" className="mx-0.5">校验</Badge> 按钮检查策略代码语法</p>
            )}

            {validation && validation.params.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-2">检测到的参数</h4>
                <div className="grid grid-cols-2 gap-2">
                  {validation.params.map(p => (
                    <div key={p.name} className="flex items-center justify-between text-xs border rounded px-2 py-1.5">
                      <span className="font-mono">{p.name}</span>
                      <span className="text-muted-foreground">{p.label} ({String(p.default)})</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="text-xs text-muted-foreground pt-4 border-t">
              <strong className="text-foreground">提示：</strong>
              <ul className="list-disc pl-4 mt-1 space-y-1">
                <li>策略类必须继承 <code className="bg-muted px-1 rounded">Strategy</code></li>
                <li>参数用 <code className="bg-muted px-1 rounded">Param(default=..., min=..., max=..., label="...")</code> 声明</li>
                <li>必须实现 <code className="bg-muted px-1 rounded">setup(self, ctx)</code> 和 <code className="bg-muted px-1 rounded">on_bar(self, ctx)</code></li>
              </ul>
            </div>
          </div>
        )}
      </div>

      {/* ===== 右侧面板 ===== */}
      <div className="w-80 space-y-3 overflow-auto flex-shrink-0">
        {/* 参数表单 */}
        {validation && validation.params.length > 0 && (
          <Card>
            <CardHeader className="py-2 px-3"><CardTitle className="text-sm flex items-center gap-1.5"><Wrench className="h-3.5 w-3.5" /> 参数</CardTitle></CardHeader>
            <CardContent className="space-y-2 px-3 pb-3">
              {validation.params.map((p) => (
                <ParamField key={p.name} p={p} value={params[p.name]}
                  onChange={(v) => setParams((prev) => ({ ...prev, [p.name]: v }))} />
              ))}
            </CardContent>
          </Card>
        )}

        {/* 回测配置 */}
        <Card>
          <CardHeader className="py-2 px-3"><CardTitle className="text-sm flex items-center gap-1.5"><Play className="h-3.5 w-3.5" /> 回测</CardTitle></CardHeader>
          <CardContent className="space-y-2 px-3 pb-3">
            <div className="flex gap-2">
              <div className="flex-1"><Label className="text-xs">起始</Label><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="h-8 text-sm" /></div>
              <div className="flex-1"><Label className="text-xs">结束</Label><Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="h-8 text-sm" /></div>
            </div>
            <div><Label className="text-xs">初始资金</Label><Input type="number" value={cash} onChange={(e) => setCash(Number(e.target.value))} className="h-8 text-sm" /></div>
            <div>
              <Label className="text-xs">成交模式</Label>
              <Select value={fillMode} onValueChange={setFillMode}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="next_open">次日开盘</SelectItem>
                  <SelectItem value="current_close">当日收盘</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button className="w-full" size="sm" onClick={run} disabled={running?.status === 'running'}>
              {running?.status === 'running' ? <><Loader2 className="h-4 w-4 mr-1 animate-spin" /> 运行中</> : <><Play className="h-4 w-4 mr-1" /> 运行回测</>}
            </Button>
            {running?.status === 'done' && (
              <Button variant="outline" size="sm" className="w-full" onClick={() => { nav(`/backtests/${running.runId}`); clearRunning(); }}>
                查看结果 <ChevronRight className="h-3 w-3 ml-1" />
              </Button>
            )}
            {running?.status === 'failed' && (
              <Button variant="outline" size="sm" className="w-full border-destructive/40 text-destructive hover:bg-destructive/10" onClick={() => { nav(`/backtests/${running.runId}`); clearRunning(); }}>
                查看错误详情 <ChevronRight className="h-3 w-3 ml-1" />
              </Button>
            )}
          </CardContent>
        </Card>

        {/* 回测历史 */}
        {!!strategyId && (
          <Card>
            <CardHeader className="py-2 px-3"><CardTitle className="text-sm flex items-center gap-1.5"><History className="h-3.5 w-3.5" /> 历史</CardTitle></CardHeader>
            <CardContent className="px-0 pb-0">
              {history && history.length > 0 ? (
                <div className="max-h-48 overflow-auto">
                  {history.slice(0, 15).map(r => (
                    <button key={r.id} onClick={() => nav(`/backtests/${r.id}`)}
                      className="w-full text-left px-3 py-1.5 text-xs hover:bg-accent transition-colors flex items-center justify-between border-b last:border-b-0">
                      <span className="flex items-center gap-2">
                        <Badge variant={r.status === 'done' ? 'default' : r.status === 'failed' ? 'destructive' : 'secondary'}
                          className="h-4 px-1 text-[10px]">
                          {r.status === 'done' ? '✓' : r.status === 'failed' ? '✗' : r.status === 'running' ? '…' : '·'}
                        </Badge>
                        <span className="font-mono text-muted-foreground">
                          {r.created_at ? new Date(r.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '?'}
                        </span>
                      </span>
                      {r.metrics && (
                        <span className={`font-mono font-medium ${(Number(r.metrics.total_return) || 0) >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                          {((Number(r.metrics.total_return) || 0) * 100).toFixed(1)}%
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground px-3 py-4">暂无回测记录</p>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
