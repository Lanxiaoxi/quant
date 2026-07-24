import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { setTokenProvider } from '@/lib/api';

interface AuthState {
  token: string | null;
  username: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      username: null,
      login: async (username: string, password: string) => {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: '登录失败' }));
          throw new Error(err.detail);
        }
        const data = await res.json();
        set({ token: data.access_token, username });
      },
      logout: () => {
        set({ token: null, username: null });
        useAuth.persist.clearStorage();
      },
    }),
    { name: 'tq-auth' }
  )
);

// 注册 token 提供者，供 api.ts 自动注入
useAuth.subscribe((s) => {
  setTokenProvider(() => s.token);
});
// 初始化
setTokenProvider(() => useAuth.getState().token);
