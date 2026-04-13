"use client";

import { useEffect, useState } from "react";
import { AgentGrid } from "@/components/dashboard/AgentGrid";
import { PRDConsole } from "@/components/dashboard/PRDConsole";
import { WorkflowPipeline } from "@/components/dashboard/WorkflowPipeline";
import { ExecutionResults } from "@/components/dashboard/ExecutionResults";
import { HUDCard } from "@/components/hud/HUDCard";
import { HUDStatus } from "@/components/hud/HUDControls";
import { submitPRD, fetchExecutions } from "@/lib/api";
import { Activity, LayoutDashboard, Settings, ExternalLink } from "lucide-react";
import { AnimatePresence } from "framer-motion";

export default function Dashboard() {
  const [executions, setExecutions] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null);

  const handlePRDSubmit = async (title: string, content: string) => {
    setLoading(true);
    try {
      await submitPRD(title, content);
      // Refresh list after brief delay for background process
      setTimeout(refresh, 1000);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    try {
      const data = await fetchExecutions(5);
      setExecutions(data.items || []);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex-1 flex flex-col max-w-7xl mx-auto w-full p-6 space-y-6">
      <AnimatePresence>
        {selectedExecutionId && (
          <ExecutionResults 
            executionId={selectedExecutionId} 
            onClose={() => setSelectedExecutionId(null)} 
          />
        )}
      </AnimatePresence>

      {/* HUD Header */}
      <header className="flex justify-between items-center border-b border-white/10 pb-4">
        <div className="flex items-center space-x-4">
          <div className="p-2 bg-hud-accent/20 rounded-sm border border-hud-accent/40 shadow-[0_0_10px_rgba(96,165,250,0.2)]">
            <LayoutDashboard className="h-5 w-5 text-hud-accent" />
          </div>
          <div>
            <h1 className="text-xl font-mono tracking-[0.3em] uppercase text-white font-bold text-glow">
             Software-Development-Factory
            </h1>
            <p className="text-[10px] font-mono text-white/30 tracking-widest uppercase">
              SEMI_AUTONOMOUS_FAC_V1.0 // SYSTEM_STABLE
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-6">
          <div className="hidden md:flex flex-col items-end">
            <span className="text-[10px] uppercase text-white/40 tracking-widest font-mono">Uptime</span>
            <span className="text-xs font-mono text-hud-accent">99.9%_NORMAL</span>
          </div>
          <Settings className="h-4 w-4 text-white/20 hover:text-white transition-colors cursor-pointer" />
        </div>
      </header>

      {/* Agents Row */}
      <section>
        <AgentGrid />
      </section>

      {/* Active Pipeline View */}
      {executions.length > 0 && executions[0].state !== 'completed' && (
        <section className="py-6 border-b border-white/5">
          <div className="flex items-center space-x-2 text-hud-accent/50 mb-6">
            <span className="text-[10px] font-mono tracking-widest uppercase">ACTIVE_LIFECYCLE_TRACKING_</span>
          </div>
          <WorkflowPipeline currentState={executions[0].state} />
        </section>
      )}

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: PRD Input */}
        <div className="lg:col-span-2">
          <PRDConsole onSubmit={handlePRDSubmit} />
        </div>

        {/* Right: Status Feed */}
        <div className="space-y-6">
          <HUDCard title="Live Stream" delay={0.3}>
            <div className="space-y-4">
              <div className="flex items-center space-x-2 text-hud-accent/50 mb-4">
                <Activity size={14} className="animate-pulse" />
                <span className="text-[10px] font-mono tracking-widest uppercase">Direct_Trace_Feed_</span>
              </div>
              
              {executions.length === 0 ? (
                <div className="py-20 text-center border border-dashed border-white/5 rounded-lg opacity-30 italic text-xs">
                  NO_ACTIVE_FLOWS_DETECTED
                </div>
              ) : (
                <div className="space-y-3">
                  {executions.map((exec, i) => (
                    <div 
                      key={exec.id} 
                      className="p-3 bg-white/5 border border-white/10 rounded group transition-all"
                    >
                      <div className="flex justify-between items-start mb-2">
                        <div className="flex flex-col">
                          <span className="text-[10px] font-mono text-white/80 tracking-widest uppercase truncate max-w-[150px]">
                            {exec.prd_title || "UNTITLED_FLOW"}
                          </span>
                          <span className="text-[8px] font-mono text-white/20 uppercase tracking-tighter">
                            ID: {exec.id.slice(0, 8)}
                          </span>
                        </div>
                        <HUDStatus status={exec.state === "completed" ? "complete" : "active"} label={exec.state} />
                      </div>
                      
                      <div className="w-full bg-white/10 h-1 rounded-full overflow-hidden mb-3">
                        <div 
                          className="bg-hud-accent h-full transition-all duration-1000 ease-in-out" 
                          style={{ width: exec.state === 'completed' ? '100%' : '65%' }} 
                        />
                      </div>

                      {exec.state === "completed" && (
                        <button
                          onClick={() => setSelectedExecutionId(exec.id)}
                          className="w-full py-1.5 border border-hud-accent/30 bg-hud-accent/5 text-[9px] font-mono text-hud-accent hover:bg-hud-accent/20 transition-all flex items-center justify-center space-x-2 uppercase tracking-widest"
                        >
                          <ExternalLink size={10} />
                          <span>View_Results_Report</span>
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </HUDCard>
        </div>
      </div>

      {/* Footer Info */}
      <footer className="mt-auto pt-6 flex justify-between items-center text-[10px] font-mono text-white/20 uppercase tracking-[0.2em] border-t border-white/5">
        <div className="flex space-x-6">
          <span>ST_NODE_01//NY_USA</span>
          <span>LATENCY: 12MS</span>
        </div>
        <div>
          ©2026_AI_CONTROL_PLANE//SYSTEM_STABLE
        </div>
      </footer>
    </div>
  );
}
