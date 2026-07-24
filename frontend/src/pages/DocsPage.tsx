/**
 * 文档模块 — 左侧导航 + 右侧 Markdown 渲染。
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowLeft, BookOpen, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { Components } from 'react-markdown';

/* ---------- 章节定义 ---------- */
interface DocSection { id: string; title: string; file: string; }
const SECTIONS: DocSection[] = [
  { id: 'overview',     title: '平台概览',       file: '01-overview' },
  { id: 'quickstart',   title: '快速开始',       file: '02-quickstart' },
  { id: 'strategy-api', title: '策略 API 参考',  file: '03-strategy-api' },
  { id: 'backtest',     title: '回测使用',       file: '04-backtest' },
  { id: 'simulation',   title: '模拟交易',       file: '05-simulation' },
  { id: 'report',       title: '报告解读',       file: '06-report' },
];

const docModules = import.meta.glob('../docs/*.md', { query: '?raw', import: 'default' });

/* ---------- markdown 组件样式 ---------- */
const mdComponents: Components = {
  h1: ({ children, ...p }) => (
    <h1 className="text-2xl font-bold mb-6 pb-2 border-b" {...p}>{children}</h1>
  ),
  h2: ({ children, ...p }) => (
    <h2 className="text-xl font-semibold mt-8 mb-4" {...p}>{children}</h2>
  ),
  h3: ({ children, ...p }) => (
    <h3 className="text-lg font-medium mt-6 mb-3" {...p}>{children}</h3>
  ),
  p: ({ children, ...p }) => (
    <p className="leading-7 my-3" {...p}>{children}</p>
  ),
  code: ({ children, className, ...p }: any) => {
    const isInline = !className;
    return isInline
      ? <code className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono" {...p}>{children}</code>
      : <code className={className} {...p}>{children}</code>;
  },
  pre: ({ children, ...p }) => (
    <pre className="bg-muted/80 border rounded-lg p-4 my-4 overflow-x-auto text-sm font-mono leading-relaxed" {...p}>{children}</pre>
  ),
  table: ({ children, ...p }) => (
    <div className="my-4 overflow-x-auto border rounded-lg">
      <table className="w-full text-sm" {...p}>{children}</table>
    </div>
  ),
  th: ({ children, ...p }) => (
    <th className="font-medium px-4 py-2.5 text-left border-b bg-muted/50" {...p}>{children}</th>
  ),
  td: ({ children, ...p }) => (
    <td className="px-4 py-2 border-b text-muted-foreground" {...p}>{children}</td>
  ),
  ul: ({ children, ...p }) => (
    <ul className="list-disc pl-6 my-3 space-y-1" {...p}>{children}</ul>
  ),
  ol: ({ children, ...p }) => (
    <ol className="list-decimal pl-6 my-3 space-y-1" {...p}>{children}</ol>
  ),
  li: ({ children, ...p }) => (
    <li className="leading-7" {...p}>{children}</li>
  ),
  blockquote: ({ children, ...p }) => (
    <blockquote className="border-l-4 border-primary bg-muted/30 py-2 px-4 rounded-r-md my-4 italic text-muted-foreground" {...p}>{children}</blockquote>
  ),
  strong: ({ children, ...p }) => (
    <strong className="font-semibold text-foreground" {...p}>{children}</strong>
  ),
  hr: () => <hr className="my-6 border-border" />,
  a: ({ children, href, ...p }) => (
    <a href={href} className="text-primary underline underline-offset-2 hover:no-underline" {...p}>{children}</a>
  ),
};

/* ---------- 组件 ---------- */
export default function DocsPage() {
  const nav = useNavigate();
  const [active, setActive] = useState(SECTIONS[0].id);
  const [contents, setContents] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadDoc = useCallback(async (id: string) => {
    if (contents[id]) return;
    setError('');
    setLoading(true);
    try {
      const section = SECTIONS.find(s => s.id === id)!;
      const key = `../docs/${section.file}.md`;
      const loader = docModules[key];
      if (!loader) { setError(`文档 "${section.title}" 未找到`); return; }
      const raw = await loader();
      setContents(prev => ({ ...prev, [id]: (raw as unknown as string) }));
    } catch {
      setError('文档加载失败，请刷新页面重试');
    } finally {
      setLoading(false);
    }
  }, [contents]);

  // 首次加载第一篇文档
  const loadFirst = useCallback(() => { loadDoc(SECTIONS[0].id); }, [loadDoc]);
  useEffect(() => { loadFirst(); }, [loadFirst]);

  const currentContent = contents[active];

  return (
    <div className="flex h-full -mx-6 -my-6">
      {/* 左侧导航 */}
      <aside className="w-48 border-r bg-muted/20 flex-shrink-0 flex flex-col">
        <h2 className="flex items-center gap-2 px-4 py-4 text-sm font-semibold text-muted-foreground border-b">
          <BookOpen className="h-4 w-4" />
          帮助文档
        </h2>
        <nav className="flex-1 py-2 overflow-auto">
          {SECTIONS.map(s => (
            <button
              key={s.id}
              onClick={() => { setActive(s.id); loadDoc(s.id); }}
              className={[
                'w-full text-left px-4 py-2 text-sm transition-colors flex items-center gap-2',
                active === s.id
                  ? 'bg-primary/10 text-primary font-medium border-r-2 border-primary'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent border-r-2 border-transparent',
              ].join(' ')}
            >
              <ChevronRight className={[
                'h-3.5 w-3.5 transition-transform flex-shrink-0',
                active === s.id ? 'rotate-90' : '',
              ].join(' ')} />
              {s.title}
            </button>
          ))}
        </nav>
      </aside>

      {/* 右侧内容 */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-3xl mx-auto py-6 px-8">
          <Button variant="ghost" size="sm" onClick={() => nav('/strategies')} className="mb-4 -ml-2">
            <ArrowLeft className="h-4 w-4 mr-1" /> 返回
          </Button>
          {loading && !currentContent ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <span className="inline-block w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
              加载中...
            </div>
          ) : error && !currentContent ? (
            <div className="text-destructive bg-destructive/10 rounded-lg px-4 py-3 text-sm">{error}</div>
          ) : currentContent ? (
            <article className="text-foreground">
              <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {currentContent}
              </Markdown>
            </article>
          ) : null}
        </div>
      </main>
    </div>
  );
}
