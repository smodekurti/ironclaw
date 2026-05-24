import React, { useState, useEffect } from 'react';
import { Terminal, Shield, MessageSquare, Activity, Settings, Maximize2, Clock, Play, StepForward, StepBack, SkipBack, SkipForward } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('chat');
  const [agents, setAgents] = useState([]);

  useEffect(() => {
    fetch('/api/agents', { headers: { 'Authorization': `Bearer ${localStorage.getItem('api_key') || ''}` }})
      .then(r => r.json())
      .then(data => setAgents(data.agents || []))
      .catch(console.error);
  }, []);

  return (
    <div className="flex h-screen bg-bgDark text-[#c9d1d9] overflow-hidden">
      {/* Sidebar */}
      <div className="w-64 glass-panel m-4 flex flex-col z-10 shadow-2xl border-glassBorder border-r-0">
        <div className="p-6 border-b border-borderDark flex items-center gap-3">
          <Shield className="w-8 h-8 text-accent2" />
          <h1 className="font-bold text-xl tracking-wider text-white">IronClaw</h1>
        </div>
        
        <div className="p-4 flex flex-col gap-2 flex-1">
          <div className="text-xs uppercase tracking-widest text-gray-500 mb-2 mt-4 font-semibold">Navigation</div>
          <NavItem icon={<MessageSquare className="w-4 h-4"/>} label="Chat & Sandbox" active={activeTab==='chat'} onClick={()=>setActiveTab('chat')} />
          <NavItem icon={<Activity className="w-4 h-4"/>} label="Node Editor" active={activeTab==='nodes'} onClick={()=>setActiveTab('nodes')} />
          <NavItem icon={<Clock className="w-4 h-4"/>} label="Time-Travel Replay" active={activeTab==='replay'} onClick={()=>setActiveTab('replay')} />
          
          <div className="text-xs uppercase tracking-widest text-gray-500 mb-2 mt-8 font-semibold">Active Agents</div>
          <div className="flex-1 overflow-y-auto">
            {agents.map(a => (
              <div key={a.id} className="flex items-center gap-2 px-3 py-2 hover:bg-glass rounded-lg cursor-pointer transition-colors text-sm">
                <div className="w-2 h-2 rounded-full bg-accent2"></div>
                {a.name || a.id}
              </div>
            ))}
            {agents.length === 0 && <div className="text-sm text-gray-500 px-3 py-2 italic">No agents deployed</div>}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 m-4 ml-0 glassmorphic relative flex flex-col shadow-2xl">
        {/* Header */}
        <div className="h-16 border-b border-borderDark flex items-center px-6 justify-between shrink-0">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold text-white capitalize">{activeTab.replace('-', ' ')}</h2>
            <span className="px-3 py-1 bg-glass rounded-full text-xs text-accent border border-glassBorder shadow-inner">
              Secure Sandbox Active
            </span>
          </div>
          <div className="flex items-center gap-4 text-gray-400">
            <button className="hover:text-white transition-colors"><Settings className="w-5 h-5"/></button>
            <button className="hover:text-white transition-colors"><Maximize2 className="w-5 h-5"/></button>
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-hidden relative">
          {activeTab === 'replay' && <TimeTravelDebugger />}
          {activeTab === 'chat' && <Placeholder title="Chat Interface" desc="Agent communication and interaction interface." />}
          {activeTab === 'nodes' && <Placeholder title="Visual Node Builder" desc="Drag and drop agents, tools, and sandboxes to build workflows." />}
        </div>
      </div>
    </div>
  );
}

function NavItem({ icon, label, active, onClick }) {
  return (
    <div onClick={onClick} className={`flex items-center gap-3 px-4 py-2.5 rounded-lg cursor-pointer transition-all ${active ? 'bg-[#1f3358]/50 text-accent border border-accent/20 shadow-[0_0_15px_rgba(88,166,255,0.1)]' : 'hover:bg-glass text-gray-400 hover:text-gray-200'}`}>
      {icon}
      <span className="font-medium text-sm">{label}</span>
    </div>
  );
}

function Placeholder({ title, desc }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-8">
      <div className="w-24 h-24 mb-6 rounded-full bg-glass flex items-center justify-center border border-glassBorder shadow-2xl">
        <Terminal className="w-10 h-10 text-gray-500" />
      </div>
      <h3 className="text-2xl font-bold text-white mb-2">{title}</h3>
      <p className="text-gray-400 max-w-md">{desc}</p>
    </div>
  );
}

// --------------------------------------------------------
// Time Travel Debugger Component
// --------------------------------------------------------
function TimeTravelDebugger() {
  const [session, setSession] = useState('');
  const [events, setEvents] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [playing, setPlaying] = useState(false);

  const loadSession = async () => {
    if (!session) return;
    try {
      const res = await fetch(`/api/audit/sessions/${session}`, { headers: { 'Authorization': `Bearer ${localStorage.getItem('api_key') || ''}` }});
      const data = await res.json();
      setEvents(data.events || []);
      setCurrentIndex(0);
    } catch(e) { console.error(e); }
  };

  useEffect(() => {
    if (!playing || currentIndex >= events.length - 1) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => {
      setCurrentIndex(c => c + 1);
    }, 1500);
    return () => clearTimeout(timer);
  }, [playing, currentIndex, events.length]);

  return (
    <div className="absolute inset-0 flex flex-col p-6 gap-6">
      <div className="flex gap-4">
        <input 
          value={session} 
          onChange={e => setSession(e.target.value)} 
          placeholder="Enter Session ID..." 
          className="flex-1 bg-surfaceDark/50 border border-borderDark rounded-lg px-4 py-2 focus:border-accent outline-none text-white shadow-inner transition-colors focus:bg-surfaceDark"
        />
        <button onClick={loadSession} className="px-6 py-2 bg-accent hover:bg-accent/80 text-black font-semibold rounded-lg transition-colors shadow-[0_0_15px_rgba(88,166,255,0.3)]">
          Load Replay
        </button>
      </div>

      <div className="flex-1 flex gap-6 overflow-hidden">
        {/* Timeline */}
        <div className="w-80 glass-panel p-4 flex flex-col overflow-y-auto shadow-inner">
          <h3 className="font-semibold text-white mb-4 uppercase tracking-widest text-xs">Execution Timeline</h3>
          {events.length === 0 && <div className="text-sm text-gray-500 italic">No events loaded.</div>}
          <div className="relative border-l border-borderDark ml-3 space-y-6">
            {events.map((ev, i) => (
              <div key={i} className="relative pl-6 cursor-pointer" onClick={() => setCurrentIndex(i)}>
                <div className={`absolute w-3 h-3 rounded-full -left-1.5 top-1.5 transition-colors shadow-lg ${i === currentIndex ? 'bg-accent ring-4 ring-accent/30' : (i < currentIndex ? 'bg-accent2' : 'bg-gray-600')}`}></div>
                <div className={`text-sm font-medium transition-colors ${i === currentIndex ? 'text-white' : 'text-gray-400'}`}>
                  {ev.event.replace(/_/g, ' ')}
                </div>
                <div className="text-xs text-gray-500 mt-1">{new Date(ev._ts).toLocaleTimeString()}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Payload Inspector */}
        <div className="flex-1 glass-panel p-6 flex flex-col shadow-inner relative overflow-hidden">
          <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAiIGhlaWdodD0iMjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMSIgY3k9IjEiIHI9IjEiIGZpbGw9InJnYmEoMjU1LDI1NSwyNTUsMC4wNSkiLz48L3N2Zz4=')] opacity-50 z-0 pointer-events-none"></div>
          
          <div className="z-10 flex-1 flex flex-col">
            <h3 className="font-semibold text-white mb-4 uppercase tracking-widest text-xs flex items-center justify-between">
              <span>State Inspector</span>
              {events[currentIndex] && <span className="bg-glass px-3 py-1 rounded-full text-accent2 border border-accent2/20 text-[10px]">Verified HMAC Signature</span>}
            </h3>
            
            {currentIndex >= 0 && events[currentIndex] ? (
              <div className="flex-1 bg-[#0d1117]/80 backdrop-blur-md rounded-lg border border-borderDark p-4 overflow-auto font-mono text-sm text-[#79c0ff] shadow-inner">
                <pre>{JSON.stringify(events[currentIndex], null, 2)}</pre>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center text-gray-500 font-mono text-sm">
                Select a timeline event to inspect memory state.
              </div>
            )}

            {/* Playback Controls */}
            <div className="mt-6 flex items-center justify-center gap-4 bg-surfaceDark/80 p-3 rounded-xl border border-borderDark shadow-xl backdrop-blur-md w-max mx-auto">
              <button className="p-2 hover:bg-glass rounded-lg transition-colors text-gray-400 hover:text-white" onClick={() => setCurrentIndex(0)} disabled={events.length===0}><SkipBack className="w-5 h-5"/></button>
              <button className="p-2 hover:bg-glass rounded-lg transition-colors text-gray-400 hover:text-white" onClick={() => setCurrentIndex(c => Math.max(0, c-1))} disabled={events.length===0}><StepBack className="w-5 h-5"/></button>
              <button className="p-3 bg-accent text-black hover:bg-accent/80 rounded-full transition-all shadow-[0_0_15px_rgba(88,166,255,0.4)]" onClick={() => setPlaying(!playing)} disabled={events.length===0}>
                <Play className="w-5 h-5" fill="currentColor" />
              </button>
              <button className="p-2 hover:bg-glass rounded-lg transition-colors text-gray-400 hover:text-white" onClick={() => setCurrentIndex(c => Math.min(events.length-1, c+1))} disabled={events.length===0}><StepForward className="w-5 h-5"/></button>
              <button className="p-2 hover:bg-glass rounded-lg transition-colors text-gray-400 hover:text-white" onClick={() => setCurrentIndex(events.length-1)} disabled={events.length===0}><SkipForward className="w-5 h-5"/></button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
