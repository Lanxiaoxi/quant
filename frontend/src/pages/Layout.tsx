import { Outlet, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Toaster } from 'sonner';
import { useAuth } from '@/stores/auth';
import { Button } from '@/components/ui/button';
import { Code, Database, TrendingUp, BookOpen, User } from 'lucide-react';

export default function Layout() {
  const { token, username, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  if (!token) return <Navigate to="/login" replace />;

  const active = (prefix: string) => pathname.startsWith(prefix);
  const nav = [
    { to: '/strategies', label: '策略', icon: <Code className="h-4 w-4" /> },
    { to: '/sims', label: '模拟', icon: <TrendingUp className="h-4 w-4" /> },
    { to: '/data', label: '数据', icon: <Database className="h-4 w-4" /> },
    { to: '/docs', label: '文档', icon: <BookOpen className="h-4 w-4" /> },
  ];

  return (
    <div className="flex h-screen bg-background">
      <aside className="w-52 min-w-[208px] border-r bg-muted/30 flex flex-col p-3">
        <h1 className="text-lg font-semibold px-3 py-4">trading-quant</h1>
        <nav className="flex-1 space-y-1">
          {nav.map((n) => (
            <Button key={n.to} variant={active(n.to) ? 'secondary' : 'ghost'}
              className="w-full justify-start gap-2 h-9" onClick={() => navigate(n.to)}>
              {n.icon} {n.label}
            </Button>
          ))}
        </nav>
        <div className="flex items-center gap-2 px-3 py-2 border-t text-sm text-muted-foreground">
          <User className="h-3 w-3" /> <span className="flex-1">{username}</span>
          <Button variant="ghost" size="sm" className="h-7 px-2" onClick={logout}>退出</Button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
      <Toaster richColors position="top-right" closeButton />
    </div>
  );
}
