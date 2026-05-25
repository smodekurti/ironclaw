import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Terminal, Shield, MessageSquare, Activity, Blocks, Clock,
  Play, StepForward, StepBack, SkipBack, SkipForward,
  Download, Send, Plus, Trash2, Settings, Maximize2,
  CheckCircle, XCircle, Loader, ChevronDown, X, Bot, Zap
} from 'lucide-react';
import { ReactFlow, Controls, Background, applyNodeChanges, applyEdgeChanges, addEdge, Panel } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

const API = (path) => path; // relative to same origin

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function authHeaders() {
  const k = localStorage.getItem('api_key') || '';
  return k ? { Authorization: `Bearer ${k}` } : {};
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(API(path), {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(opts.headers || {}) },
  });
  return res;
}

// ---------------------------------------------------------------------------
// Root App
// ---------------------------------------------------------------------------
export default function App() {
  const [activeTab, setActiveTab] = useState('chat');
  const [agents, setAgents] = useState([]);

  const refreshAgents = useCallback(async () => {
    try {
      const res = await apiFetch('/api/agents');
      if (res.ok) {
        const data = await res.json();
        setAgents(data.agents || []);
      }
    } catch {}
  }, []);

  useEffect(() => { refreshAgents(); }, [refreshAgents]);

  return (
    <div className="flex h-screen bg-bgDark text-[#c9d1d9] overflow-hidden">
      {/* Sidebar */}
      <div className="w-60 shrink-0 flex flex-col border-r border-borderDark">
        <div className="p-5 border-b border-borderDark flex items-center gap-3">
          <Shield className="w-7 h-7 text-accent2 shrink-0" />
          <h1 className="font-bold text-lg tracking-wide text-white">IronClaw</h1>
        </div>

        <div className="p-3 flex flex-col gap-1">
          <p className="text-xs uppercase tracking-widest text-gray-500 mb-1 mt-3 px-2 font-semibold">Navigation</p>
          <NavItem icon={<MessageSquare className="w-4 h-4" />} label="Chat & Sandbox" active={activeTab === 'chat'} onClick={() => setActiveTab('chat')} />
          <NavItem icon={<Activity className="w-4 h-4" />} label="Visual Node Builder" active={activeTab === 'nodes'} onClick={() => setActiveTab('nodes')} />
          <NavItem icon={<Blocks className="w-4 h-4" />} label="Skill Marketplace" active={activeTab === 'skills'} onClick={() => setActiveTab('skills')} />
          <NavItem icon={<Clock className="w-4 h-4" />} label="Time-Travel Replay" active={activeTab === 'replay'} onClick={() => setActiveTab('replay')} />

          <p className="text-xs uppercase tracking-widest text-gray-500 mb-1 mt-5 px-2 font-semibold">Active Agents</p>
          <div className="flex-1 overflow-y-auto space-y-0.5">
            {agents.map(a => (
              <div key={a.id || a.agent_id} className="flex items-center gap-2 px-3 py-2 hover:bg-glass rounded-lg cursor-pointer text-sm text-gray-300 hover:text-white transition-colors">
                <div className="w-1.5 h-1.5 rounded-full bg-accent2 shrink-0" />
                {a.name || a.id || a.agent_id}
              </div>
            ))}
            {agents.length === 0 && <p className="text-xs text-gray-500 px-3 py-2 italic">No agents deployed</p>}
          </div>
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="h-14 border-b border-borderDark flex items-center px-6 justify-between shrink-0">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold text-white capitalize">{activeTab.replace('-', ' ')}</h2>
            <span className="px-2.5 py-0.5 bg-accent2/10 border border-accent2/30 rounded-full text-xs text-accent2">Secure Sandbox Active</span>
          </div>
          <div className="flex items-center gap-3 text-gray-400">
            <button className="hover:text-white transition-colors p-1"><Settings className="w-4 h-4" /></button>
            <button className="hover:text-white transition-colors p-1"><Maximize2 className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="flex-1 overflow-hidden">
          {activeTab === 'chat' && <ChatSandbox agents={agents} onAgentCreated={refreshAgents} />}
          {activeTab === 'nodes' && <VisualNodeBuilder onAgentCreated={refreshAgents} />}
          {activeTab === 'skills' && <SkillMarketplace />}
          {activeTab === 'replay' && <TimeTravelDebugger />}
        </div>
      </div>
    </div>
  );
}

function NavItem({ icon, label, active, onClick }) {
  return (
    <button onClick={onClick} className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all text-left ${active ? 'bg-accent/10 text-accent border border-accent/20' : 'text-gray-400 hover:bg-glass hover:text-gray-200'}`}>
      {icon}<span>{label}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Chat & Sandbox — fully functional SSE chat
// ---------------------------------------------------------------------------
const PROVIDERS = ['anthropic', 'openai', 'gemini', 'groq', 'mistral', 'together', 'ollama'];
const MODELS = {
  anthropic: ['claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5-20251001'],
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
  gemini: ['gemini-1.5-pro', 'gemini-1.5-flash'],
  groq: ['llama-3.3-70b-versatile', 'mixtral-8x7b-32768'],
  mistral: ['mistral-large-latest', 'mistral-medium-latest'],
  together: ['meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo'],
  ollama: [], // free-text — type your local model name
};

function ChatSandbox({ agents, onAgentCreated }) {
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [form, setForm] = useState({
    agent_id: '', name: '', system_prompt: 'You are a helpful assistant.',
    provider: 'anthropic', model: 'claude-sonnet-4-6', api_key: '',
    tools: [], capabilities: ['*'],
  });
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const createAgent = async () => {
    if (!form.agent_id.trim()) { setCreateError('Agent ID is required'); return; }
    setCreating(true); setCreateError('');
    try {
      const res = await apiFetch('/api/agents', {
        method: 'POST', body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) { setCreateError(data.detail || 'Failed to create agent'); setCreating(false); return; }
      setSelectedAgentId(form.agent_id);
      setMessages([]);
      setShowCreate(false);
      onAgentCreated();
    } catch (e) { setCreateError(String(e)); }
    setCreating(false);
  };

  const sendMessage = async () => {
    if (!input.trim() || !selectedAgentId || streaming) return;
    const text = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setStreaming(true);
    const assistantIndex = messages.length + 1;
    setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

    try {
      const res = await fetch(`/api/agents/${selectedAgentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ message: text }),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const part of parts) {
          if (part.startsWith('data: ')) {
            try {
              const ev = JSON.parse(part.slice(6));
              if (ev.type === 'token') {
                setMessages(prev => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  updated[updated.length - 1] = { ...last, content: last.content + ev.text };
                  return updated;
                });
              } else if (ev.type === 'error') {
                setMessages(prev => {
                  const updated = [...prev];
                  updated[updated.length - 1] = { role: 'error', content: ev.message };
                  return updated;
                });
              }
            } catch {}
          }
        }
      }
    } catch (e) {
      setMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'error', content: String(e) }; return u; });
    }
    setStreaming(false);
    setTimeout(() => inputRef.current?.focus(), 50);
  };

  const clearHistory = async () => {
    if (!selectedAgentId) return;
    await apiFetch(`/api/agents/${selectedAgentId}/clear`, { method: 'POST' });
    setMessages([]);
  };

  const handleKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } };

  return (
    <div className="h-full flex flex-col">
      {/* Agent bar */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-borderDark bg-surfaceDark/40 shrink-0">
        <Bot className="w-4 h-4 text-gray-400 shrink-0" />
        <select
          value={selectedAgentId}
          onChange={e => { setSelectedAgentId(e.target.value); setMessages([]); }}
          className="flex-1 bg-transparent text-sm text-gray-200 outline-none cursor-pointer"
        >
          <option value="">— select an agent —</option>
          {agents.map(a => (
            <option key={a.id || a.agent_id} value={a.id || a.agent_id}>{a.name || a.id || a.agent_id}</option>
          ))}
        </select>
        {selectedAgentId && (
          <button onClick={clearHistory} className="text-xs text-gray-500 hover:text-gray-300 transition-colors px-2 py-1 rounded border border-borderDark hover:border-gray-500">Clear</button>
        )}
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-black text-xs font-semibold rounded-lg hover:bg-accent/80 transition-colors shadow-sm"
        >
          <Plus className="w-3.5 h-3.5" /> New Agent
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && !selectedAgentId && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-16 h-16 rounded-full bg-glass border border-glassBorder flex items-center justify-center mb-4">
              <Terminal className="w-7 h-7 text-gray-500" />
            </div>
            <p className="text-gray-400 text-sm">Select an agent or create one to start chatting</p>
          </div>
        )}
        {messages.length === 0 && selectedAgentId && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Zap className="w-8 h-8 text-accent/50 mb-3" />
            <p className="text-gray-400 text-sm">Send a message to start</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatBubble key={i} msg={msg} isLast={i === messages.length - 1} streaming={streaming} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-borderDark px-4 py-3 bg-surfaceDark/30">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            disabled={!selectedAgentId || streaming}
            rows={1}
            placeholder={selectedAgentId ? 'Message the agent… (Enter to send)' : 'Select an agent first'}
            className="flex-1 bg-surfaceDark border border-borderDark rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-600 outline-none focus:border-accent/50 resize-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ maxHeight: '120px', overflowY: 'auto' }}
          />
          <button
            onClick={sendMessage}
            disabled={!selectedAgentId || !input.trim() || streaming}
            className="shrink-0 w-10 h-10 flex items-center justify-center rounded-xl bg-accent text-black hover:bg-accent/80 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-sm"
          >
            {streaming ? <Loader className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Create Agent Modal */}
      {showCreate && (
        <Modal title="Create New Agent" onClose={() => { setShowCreate(false); setCreateError(''); }}>
          <div className="space-y-3">
            <Field label="Agent ID" required>
              <input value={form.agent_id} onChange={e => setForm(f => ({ ...f, agent_id: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }))}
                placeholder="my-agent" className={inputCls} />
            </Field>
            <Field label="Display Name">
              <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="My Agent" className={inputCls} />
            </Field>
            <Field label="Provider">
              <select value={form.provider} onChange={e => setForm(f => ({ ...f, provider: e.target.value, model: MODELS[e.target.value]?.[0] || '' }))} className={inputCls}>
                {PROVIDERS.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </Field>
            <Field label="Model">
              {form.provider === 'ollama' ? (
                <input value={form.model} onChange={e => setForm(f => ({ ...f, model: e.target.value }))}
                  placeholder="e.g. llama3.3:70b, gemma4:latest, mistral" className={inputCls} />
              ) : (
                <select value={form.model} onChange={e => setForm(f => ({ ...f, model: e.target.value }))} className={inputCls}>
                  {(MODELS[form.provider] || []).map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              )}
            </Field>
            <Field label="API Key">
              <input type="password" value={form.api_key} onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))}
                placeholder="sk-… (leave blank to use env var)" className={inputCls} />
            </Field>
            <Field label="System Prompt">
              <textarea value={form.system_prompt} onChange={e => setForm(f => ({ ...f, system_prompt: e.target.value }))}
                rows={3} className={inputCls + ' resize-none'} />
            </Field>
            <Field label="Tools">
              <div className="flex gap-3">
                {['web', 'filesystem', 'shell'].map(t => (
                  <label key={t} className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
                    <input type="checkbox" checked={form.tools.includes(t)}
                      onChange={e => setForm(f => ({ ...f, tools: e.target.checked ? [...f.tools, t] : f.tools.filter(x => x !== t) }))}
                      className="accent-accent" />
                    {t}
                  </label>
                ))}
              </div>
            </Field>
            {createError && <p className="text-red-400 text-xs">{createError}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => { setShowCreate(false); setCreateError(''); }} className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors">Cancel</button>
              <button onClick={createAgent} disabled={creating} className="px-4 py-2 text-sm bg-accent text-black font-semibold rounded-lg hover:bg-accent/80 disabled:opacity-50 transition-colors">
                {creating ? 'Creating…' : 'Create Agent'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ChatBubble({ msg, isLast, streaming }) {
  const isUser = msg.role === 'user';
  const isError = msg.role === 'error';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
        isUser ? 'bg-accent text-black rounded-br-sm'
        : isError ? 'bg-red-900/40 border border-red-700/40 text-red-300 rounded-bl-sm'
        : 'bg-surfaceDark border border-borderDark text-gray-200 rounded-bl-sm'
      }`}>
        {msg.content || (isLast && streaming ? <span className="inline-block w-2 h-4 bg-current animate-pulse rounded" /> : null)}
        {isLast && streaming && msg.content && <span className="inline-block w-1.5 h-4 bg-current animate-pulse rounded ml-0.5 align-text-bottom" />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Visual Node Builder — functional Add / Deploy
// ---------------------------------------------------------------------------
const NODE_COLORS = { provider: '#1f3358', tool: '#1a2a1a', output: '#2a1a2a' };

let nodeIdCounter = 10;

const nodeTypes = {};

function VisualNodeBuilder({ onAgentCreated }) {
  const [nodes, setNodes] = useState([
    { id: '1', position: { x: 100, y: 150 }, data: { label: 'Provider (Anthropic)', type: 'provider', provider: 'anthropic', model: 'claude-sonnet-4-6', api_key: '' }, style: { background: NODE_COLORS.provider, color: '#58a6ff', border: '1px solid #30363d', borderRadius: 8, padding: '10px 16px' } },
    { id: '2', position: { x: 380, y: 150 }, data: { label: 'Agent: Web Researcher', type: 'agent' }, style: { background: '#161b22', color: '#c9d1d9', border: '1px solid #30363d', borderRadius: 8, padding: '10px 16px' } },
    { id: '3', position: { x: 100, y: 300 }, data: { label: 'Tool: Web Search', type: 'tool', tool: 'web' }, style: { background: NODE_COLORS.tool, color: '#3fb950', border: '1px solid #30363d', borderRadius: 8, padding: '10px 16px' } },
    { id: '4', position: { x: 660, y: 150 }, data: { label: 'Output (Memory)', type: 'output' }, type: 'output', style: { background: NODE_COLORS.output, color: '#d2a8ff', border: '1px solid #30363d', borderRadius: 8, padding: '10px 16px' } },
  ]);
  const [edges, setEdges] = useState([
    { id: 'e1-2', source: '1', target: '2' },
    { id: 'e3-2', source: '3', target: '2', animated: true },
    { id: 'e2-4', source: '2', target: '4' },
  ]);
  const [selected, setSelected] = useState(null);
  const [deploying, setDeploying] = useState(false);
  const [deployStatus, setDeployStatus] = useState(null); // { ok, message }

  const onNodesChange = useCallback(chs => setNodes(nds => applyNodeChanges(chs, nds)), []);
  const onEdgesChange = useCallback(chs => setEdges(eds => applyEdgeChanges(chs, eds)), []);
  const onConnect = useCallback(params => setEdges(eds => addEdge({ ...params, animated: true }, eds)), []);
  const onNodeClick = useCallback((_, node) => setSelected(node), []);

  const addProviderNode = () => {
    const id = String(++nodeIdCounter);
    setNodes(nds => [...nds, {
      id, position: { x: 120 + Math.random() * 80, y: 120 + Math.random() * 80 },
      data: { label: 'Provider (Anthropic)', type: 'provider', provider: 'anthropic', model: 'claude-sonnet-4-6', api_key: '', agent_id: `agent-${id}`, name: `Agent ${id}` },
      style: { background: NODE_COLORS.provider, color: '#58a6ff', border: '1px solid #30363d', borderRadius: 8, padding: '10px 16px' },
    }]);
  };

  const addToolNode = () => {
    const id = String(++nodeIdCounter);
    setNodes(nds => [...nds, {
      id, position: { x: 120 + Math.random() * 80, y: 300 + Math.random() * 80 },
      data: { label: 'Tool: Web', type: 'tool', tool: 'web' },
      style: { background: NODE_COLORS.tool, color: '#3fb950', border: '1px solid #30363d', borderRadius: 8, padding: '10px 16px' },
    }]);
  };

  const deployFlow = async () => {
    setDeploying(true); setDeployStatus(null);
    // Find all provider nodes and deploy them as agents
    const providerNodes = nodes.filter(n => n.data?.type === 'provider');
    if (providerNodes.length === 0) {
      setDeployStatus({ ok: false, message: 'No provider nodes found. Add a Provider Node first.' });
      setDeploying(false); return;
    }
    const results = [];
    for (const node of providerNodes) {
      // Find tool nodes connected to this node's downstream agent
      const connectedToolEdges = edges.filter(e => e.target === node.id || e.source === node.id);
      const toolNodeIds = connectedToolEdges.map(e => e.source === node.id ? e.target : e.source);
      const tools = nodes.filter(n => toolNodeIds.includes(n.id) && n.data?.type === 'tool').map(n => n.data.tool).filter(Boolean);

      const agentId = (node.data.agent_id || `flow-agent-${node.id}`).toLowerCase().replace(/[^a-z0-9-]/g, '-');
      const payload = {
        agent_id: agentId,
        name: node.data.name || agentId,
        provider: node.data.provider || 'anthropic',
        model: node.data.model || '',
        api_key: node.data.api_key || '',
        tools,
        capabilities: ['*'],
        system_prompt: 'You are a helpful assistant.',
      };
      const res = await apiFetch('/api/agents', { method: 'POST', body: JSON.stringify(payload) });
      const data = await res.json();
      results.push({ id: agentId, ok: res.ok, msg: res.ok ? 'deployed' : (data.detail || 'error') });
    }
    const allOk = results.every(r => r.ok);
    setDeployStatus({ ok: allOk, message: results.map(r => `${r.id}: ${r.msg}`).join(' | ') });
    if (allOk) onAgentCreated();
    setDeploying(false);
  };

  const updateSelected = (key, val) => {
    if (!selected) return;
    setNodes(nds => nds.map(n => {
      if (n.id !== selected.id) return n;
      const newData = { ...n.data, [key]: val };
      // Update label too
      if (key === 'provider') newData.label = `Provider (${val})`;
      if (key === 'tool') newData.label = `Tool: ${val}`;
      if (key === 'name') newData.label = val || n.data.label;
      return { ...n, data: newData };
    }));
    setSelected(s => ({ ...s, data: { ...s.data, [key]: val } }));
  };

  return (
    <div className="h-full flex">
      <div className="flex-1" style={{ background: '#0d1117' }}>
        <ReactFlow
          nodes={nodes} edges={edges}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onConnect={onConnect} onNodeClick={onNodeClick}
          fitView
        >
          <Background color="#30363d" gap={16} />
          <Controls />
          <Panel position="top-left">
            <div className="flex gap-2 mt-1 ml-1">
              <button onClick={addProviderNode} className="px-3 py-1.5 bg-[#1f3358] border border-accent/30 text-accent text-xs font-medium rounded-lg hover:bg-accent/20 transition-colors">+ Provider Node</button>
              <button onClick={addToolNode} className="px-3 py-1.5 bg-[#1a2a1a] border border-accent2/30 text-accent2 text-xs font-medium rounded-lg hover:bg-accent2/20 transition-colors">+ Tool Node</button>
            </div>
          </Panel>
          <Panel position="top-right">
            <div className="flex flex-col items-end gap-2 mt-1 mr-1">
              <button onClick={deployFlow} disabled={deploying} className="px-4 py-1.5 bg-accent text-black text-xs font-semibold rounded-lg hover:bg-accent/80 disabled:opacity-50 transition-colors shadow-md">
                {deploying ? 'Deploying…' : 'Deploy Flow'}
              </button>
              {deployStatus && (
                <div className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border ${deployStatus.ok ? 'bg-accent2/10 border-accent2/30 text-accent2' : 'bg-red-900/20 border-red-700/30 text-red-400'}`}>
                  {deployStatus.ok ? <CheckCircle className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
                  {deployStatus.message}
                </div>
              )}
            </div>
          </Panel>
        </ReactFlow>
      </div>

      {/* Config panel */}
      {selected && selected.data?.type === 'provider' && (
        <div className="w-64 shrink-0 border-l border-borderDark bg-surfaceDark/60 p-4 flex flex-col gap-3 overflow-y-auto">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white">Configure Node</h3>
            <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-white"><X className="w-4 h-4" /></button>
          </div>
          <Field label="Agent ID">
            <input value={selected.data.agent_id || ''} onChange={e => updateSelected('agent_id', e.target.value)} className={inputCls} placeholder="my-agent" />
          </Field>
          <Field label="Display Name">
            <input value={selected.data.name || ''} onChange={e => updateSelected('name', e.target.value)} className={inputCls} placeholder="My Agent" />
          </Field>
          <Field label="Provider">
            <select value={selected.data.provider || 'anthropic'} onChange={e => updateSelected('provider', e.target.value)} className={inputCls}>
              {PROVIDERS.map(p => <option key={p}>{p}</option>)}
            </select>
          </Field>
          <Field label="Model">
            <input value={selected.data.model || ''} onChange={e => updateSelected('model', e.target.value)} className={inputCls} placeholder="claude-sonnet-4-6" />
          </Field>
          <Field label="API Key">
            <input type="password" value={selected.data.api_key || ''} onChange={e => updateSelected('api_key', e.target.value)} className={inputCls} placeholder="sk-… or blank for env var" />
          </Field>
        </div>
      )}
      {selected && selected.data?.type === 'tool' && (
        <div className="w-64 shrink-0 border-l border-borderDark bg-surfaceDark/60 p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white">Configure Tool</h3>
            <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-white"><X className="w-4 h-4" /></button>
          </div>
          <Field label="Tool Bundle">
            <select value={selected.data.tool || 'web'} onChange={e => updateSelected('tool', e.target.value)} className={inputCls}>
              <option value="web">web</option>
              <option value="filesystem">filesystem</option>
              <option value="shell">shell</option>
            </select>
          </Field>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill Marketplace — real install with inline status
// ---------------------------------------------------------------------------
function SkillMarketplace() {
  const [skills, setSkills] = useState([]);
  const [installing, setInstalling] = useState({});
  const [installStatus, setInstallStatus] = useState({});
  const [customUrl, setCustomUrl] = useState('');

  useEffect(() => {
    apiFetch('/api/skills').then(r => r.json()).then(d => setSkills(d.skills || [])).catch(() => {});
  }, []);

  const install = async (name, url) => {
    const key = name || url;
    setInstalling(s => ({ ...s, [key]: true }));
    setInstallStatus(s => ({ ...s, [key]: null }));
    try {
      const res = await apiFetch('/api/skills/install', { method: 'POST', body: JSON.stringify({ url }) });
      const data = await res.json();
      if (res.ok) {
        setInstallStatus(s => ({ ...s, [key]: { ok: true, msg: `Installed: ${data.name}` } }));
      } else {
        setInstallStatus(s => ({ ...s, [key]: { ok: false, msg: data.detail || 'Install failed' } }));
      }
    } catch (e) {
      setInstallStatus(s => ({ ...s, [key]: { ok: false, msg: String(e) } }));
    }
    setInstalling(s => ({ ...s, [key]: false }));
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold text-white">Skill Marketplace</h2>
        <div className="flex gap-2">
          <input value={customUrl} onChange={e => setCustomUrl(e.target.value)} placeholder="https://github.com/org/skill-repo"
            className="w-72 bg-surfaceDark border border-borderDark rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-accent/50 placeholder-gray-600" />
          <button onClick={() => customUrl && install(customUrl, customUrl)} disabled={!customUrl || installing[customUrl]}
            className="px-3 py-1.5 bg-accent text-black text-xs font-semibold rounded-lg hover:bg-accent/80 disabled:opacity-50 transition-colors">
            Install from URL
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {skills.map((s, i) => {
          const status = installStatus[s.name];
          const busy = installing[s.name];
          return (
            <div key={i} className="bg-surfaceDark border border-borderDark rounded-xl p-5 flex flex-col hover:border-gray-600 transition-colors">
              <div className="flex items-start justify-between mb-2">
                <h3 className="text-sm font-bold text-white">{s.name}</h3>
                <span className="text-xs text-accent2 bg-accent2/10 border border-accent2/20 px-2 py-0.5 rounded-full shrink-0 ml-2">Local</span>
              </div>
              <p className="text-xs text-gray-400 flex-1 mb-4 leading-relaxed">{s.description || 'No description provided.'}</p>
              {status && (
                <div className={`flex items-center gap-1.5 text-xs mb-2 ${status.ok ? 'text-accent2' : 'text-red-400'}`}>
                  {status.ok ? <CheckCircle className="w-3.5 h-3.5 shrink-0" /> : <XCircle className="w-3.5 h-3.5 shrink-0" />}
                  <span className="truncate">{status.msg}</span>
                </div>
              )}
              <button onClick={() => install(s.name, `https://agentskills.io/${s.name}`)} disabled={busy}
                className="flex items-center justify-center gap-1.5 text-xs text-gray-400 hover:text-white transition-colors py-1.5 border border-borderDark rounded-lg hover:border-gray-500 disabled:opacity-50">
                {busy ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                {busy ? 'Installing…' : 'Install Update'}
              </button>
            </div>
          );
        })}

        {/* Remote skill card */}
        {(() => {
          const key = 'jira-manager';
          const status = installStatus[key];
          const busy = installing[key];
          return (
            <div className="bg-surfaceDark border border-dashed border-gray-600 rounded-xl p-5 flex flex-col hover:border-gray-500 transition-colors">
              <div className="flex items-start justify-between mb-2">
                <h3 className="text-sm font-bold text-white">jira-manager</h3>
                <span className="text-xs text-accent bg-accent/10 border border-accent/20 px-2 py-0.5 rounded-full shrink-0 ml-2">Remote</span>
              </div>
              <p className="text-xs text-gray-400 flex-1 mb-4 leading-relaxed">Manage Jira tickets, transition states, and add comments.</p>
              <p className="text-xs text-gray-600 mb-3">agentskills.io</p>
              {status && (
                <div className={`flex items-center gap-1.5 text-xs mb-2 ${status.ok ? 'text-accent2' : 'text-red-400'}`}>
                  {status.ok ? <CheckCircle className="w-3.5 h-3.5 shrink-0" /> : <XCircle className="w-3.5 h-3.5 shrink-0" />}
                  <span className="truncate">{status.msg}</span>
                </div>
              )}
              <button onClick={() => install(key, `https://agentskills.io/${key}`)} disabled={busy}
                className="flex items-center justify-center gap-1.5 text-xs text-accent hover:text-white transition-colors py-1.5 border border-accent/30 rounded-lg hover:border-accent disabled:opacity-50">
                {busy ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                {busy ? 'Installing…' : '1-Click Install'}
              </button>
            </div>
          );
        })()}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Time-Travel Debugger
// ---------------------------------------------------------------------------
function TimeTravelDebugger() {
  const [session, setSession] = useState('');
  const [events, setEvents] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);

  const loadSession = async () => {
    if (!session) return;
    setLoading(true);
    try {
      const res = await apiFetch(`/api/audit/sessions/${session}`);
      const data = await res.json();
      setEvents(data.events || []);
      setCurrentIndex(data.events?.length ? 0 : -1);
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    if (!playing || currentIndex >= events.length - 1) { setPlaying(false); return; }
    const t = setTimeout(() => setCurrentIndex(c => c + 1), 1200);
    return () => clearTimeout(t);
  }, [playing, currentIndex, events.length]);

  return (
    <div className="h-full flex flex-col p-4 gap-4">
      <div className="flex gap-3 shrink-0">
        <input value={session} onChange={e => setSession(e.target.value)} onKeyDown={e => e.key === 'Enter' && loadSession()}
          placeholder="Enter session ID…"
          className="flex-1 bg-surfaceDark border border-borderDark rounded-lg px-4 py-2 text-sm text-white outline-none focus:border-accent/50 placeholder-gray-600" />
        <button onClick={loadSession} disabled={loading || !session}
          className="px-5 py-2 bg-accent text-black text-sm font-semibold rounded-lg hover:bg-accent/80 disabled:opacity-50 transition-colors">
          {loading ? 'Loading…' : 'Load Replay'}
        </button>
      </div>

      <div className="flex-1 flex gap-4 overflow-hidden min-h-0">
        {/* Timeline */}
        <div className="w-72 shrink-0 bg-surfaceDark border border-borderDark rounded-xl p-4 flex flex-col overflow-hidden">
          <h3 className="text-xs uppercase tracking-widest text-gray-500 font-semibold mb-4">Execution Timeline</h3>
          {events.length === 0
            ? <p className="text-xs text-gray-500 italic">No events loaded.</p>
            : <div className="overflow-y-auto flex-1 relative border-l border-borderDark ml-2 space-y-4 pl-5">
                {events.map((ev, i) => (
                  <div key={i} onClick={() => setCurrentIndex(i)} className="relative cursor-pointer group">
                    <div className={`absolute w-2.5 h-2.5 rounded-full -left-[1.45rem] top-1.5 transition-all ${i === currentIndex ? 'bg-accent ring-4 ring-accent/20' : i < currentIndex ? 'bg-accent2' : 'bg-gray-600 group-hover:bg-gray-400'}`} />
                    <p className={`text-xs font-medium transition-colors ${i === currentIndex ? 'text-white' : 'text-gray-400 group-hover:text-gray-200'}`}>{(ev.event || '').replace(/_/g, ' ')}</p>
                    <p className="text-xs text-gray-600 mt-0.5">{ev._ts ? new Date(ev._ts * 1000).toLocaleTimeString() : ''}</p>
                  </div>
                ))}
              </div>
          }
        </div>

        {/* Inspector */}
        <div className="flex-1 bg-surfaceDark border border-borderDark rounded-xl p-4 flex flex-col overflow-hidden">
          <h3 className="text-xs uppercase tracking-widest text-gray-500 font-semibold mb-4">State Inspector</h3>
          {currentIndex >= 0 && events[currentIndex]
            ? <pre className="flex-1 overflow-auto text-xs text-[#79c0ff] font-mono leading-relaxed">{JSON.stringify(events[currentIndex], null, 2)}</pre>
            : <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">Select a timeline event to inspect</div>
          }
          <div className="mt-4 flex items-center justify-center gap-2 pt-3 border-t border-borderDark">
            {[
              { icon: <SkipBack className="w-4 h-4" />, fn: () => setCurrentIndex(0) },
              { icon: <StepBack className="w-4 h-4" />, fn: () => setCurrentIndex(c => Math.max(0, c - 1)) },
              { icon: <Play className="w-4 h-4" fill="currentColor" />, fn: () => setPlaying(p => !p), active: playing },
              { icon: <StepForward className="w-4 h-4" />, fn: () => setCurrentIndex(c => Math.min(events.length - 1, c + 1)) },
              { icon: <SkipForward className="w-4 h-4" />, fn: () => setCurrentIndex(events.length - 1) },
            ].map((btn, i) => (
              <button key={i} onClick={btn.fn} disabled={events.length === 0}
                className={`p-2 rounded-lg transition-colors disabled:opacity-30 ${btn.active ? 'bg-accent text-black' : 'text-gray-400 hover:bg-glass hover:text-white'}`}>
                {btn.icon}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared UI primitives
// ---------------------------------------------------------------------------
const inputCls = 'w-full bg-bgDark border border-borderDark rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-accent/50 transition-colors';

function Field({ label, children, required }) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}{required && <span className="text-red-400 ml-0.5">*</span>}</label>
      {children}
    </div>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-surfaceDark border border-borderDark rounded-2xl w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-borderDark">
          <h2 className="text-sm font-bold text-white">{title}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
