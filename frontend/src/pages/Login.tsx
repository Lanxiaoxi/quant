import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '@/stores/auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function Login() {
  const [user, setUser] = useState('');
  const [pass, setPass] = useState('');
  const [err, setErr] = useState('');
  const { login, token } = useAuth();
  const nav = useNavigate();
  if (token) return <Navigate to="/strategies" replace />;

  const submit = async () => {
    setErr('');
    try {
      await login(user, pass);
      nav('/strategies', { replace: true });
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '登录失败');
    }
  };

  return (
    <div className="flex items-center justify-center h-screen bg-muted/30">
      <Card className="w-96">
        <CardHeader>
          <CardTitle className="text-center">trading-quant</CardTitle>
          <p className="text-sm text-center text-muted-foreground">量化回测平台</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input placeholder="用户名" value={user} onChange={(e) => setUser(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()} />
          <Input type="password" placeholder="密码" value={pass} onChange={(e) => setPass(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()} />
          {err && <p className="text-sm text-destructive">{err}</p>}
          <Button className="w-full" onClick={submit} disabled={!user || !pass}>登录</Button>
        </CardContent>
      </Card>
    </div>
  );
}
