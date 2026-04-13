"use client";

import { useEffect, useState } from "react";
import { HUDCard } from "@/components/hud/HUDCard";
import { HUDButton } from "@/components/hud/HUDControls";
import { fetchArtifacts } from "@/lib/api";
import { FileCode, FileText, CheckCircle2, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface ExecutionResultsProps {
  executionId: string;
  onClose: () => void;
}

export function ExecutionResults({ executionId, onClose }: ExecutionResultsProps) {
  const [activeTab, setActiveTab] = useState<"spec" | "code" | "validation">("spec");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        const result = await fetchArtifacts(executionId, activeTab);
        setData(result);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [executionId, activeTab]);

  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 md:p-10"
    >
      <HUDCard 
        title={`Execution Results // ${executionId.slice(0, 8)}`} 
        glow 
        className="w-full max-w-5xl h-[80vh] flex flex-col"
      >
        <div className="absolute top-4 right-4">
          <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex space-x-2 border-b border-white/10 mb-6">
          <TabButton 
            active={activeTab === "spec"} 
            onClick={() => setActiveTab("spec")}
            icon={<FileText size={14} />}
            label="Specification"
          />
          <TabButton 
            active={activeTab === "code"} 
            onClick={() => setActiveTab("code")}
            icon={<FileCode size={14} />}
            label="Generated Code"
          />
          <TabButton 
            active={activeTab === "validation"} 
            onClick={() => setActiveTab("validation")}
            icon={<CheckCircle2 size={14} />}
            label="Validation"
          />
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-auto bg-black/20 rounded border border-white/5 p-4 font-mono text-sm relative">
          {loading ? (
            <div className="flex items-center justify-center h-full text-hud-accent/50 animate-pulse">
              FETCHING_ARTIFACT_DATA...
            </div>
          ) : data ? (
            <div className="space-y-4">
              {activeTab === "spec" && (
                <pre className="whitespace-pre-wrap text-blue-300">
                  {JSON.stringify(data, null, 2)}
                </pre>
              )}
              {activeTab === "code" && (
                <div className="space-y-6">
                  {/* Since artifact might be an array or single object depending on backend */}
                  {Array.isArray(data) ? data.map((art: any) => (
                    <div key={art.id} className="space-y-2">
                       <div className="text-[10px] text-hud-accent/60 uppercase tracking-widest bg-hud-accent/5 px-2 py-1 rounded w-fit">
                         FILE: {art.file_path}
                       </div>
                       <pre className="p-4 bg-white/5 rounded border border-white/10 overflow-x-auto text-green-300">
                         {art.content}
                       </pre>
                    </div>
                  )) : (
                    <pre className="text-green-300">{JSON.stringify(data, null, 2)}</pre>
                  )}
                </div>
              )}
              {activeTab === "validation" && (
                <pre className="text-purple-300">
                  {JSON.stringify(data, null, 2)}
                </pre>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-white/20 italic">
              NO_ARTIFACT_DATA_AVAILABLE
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-end">
          <HUDButton onClick={onClose} variant="secondary">CLOSE_REPORTS</HUDButton>
        </div>
      </HUDCard>
    </motion.div>
  );
}

function TabButton({ active, onClick, icon, label }: any) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center space-x-2 px-4 py-2 text-[10px] uppercase font-mono tracking-widest transition-all border-b-2 ${
        active 
          ? "text-hud-accent border-hud-accent bg-hud-accent/10" 
          : "text-white/40 border-transparent hover:text-white/60 hover:bg-white/5"
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
