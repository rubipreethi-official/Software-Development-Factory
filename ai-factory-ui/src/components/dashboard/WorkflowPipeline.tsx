"use client";

import { motion } from "framer-motion";
import { Brain, Code, ShieldCheck, Zap } from "lucide-react";
import { cn } from "@/lib/utils";

const states = [
  { id: "spec_generation", name: "Atlas", role: "Spec Architect", icon: Brain },
  { id: "api_design", name: "Vector", role: "API Designer", icon: Zap },
  { id: "logic_implementation", name: "Core", role: "Logic Engineer", icon: Code },
  { id: "testing", name: "Guard", role: "QA Specialist", icon: ShieldCheck },
];

export function WorkflowPipeline({ currentState }: { currentState: string }) {
  const currentIndex = states.findIndex(s => s.id === currentState || s.id === currentState.replace("spec_", "spec_").replace("logic_", "logic_"));
  const activeIndex = currentIndex === -1 ? 0 : currentIndex;

  return (
    <div className="flex flex-col md:flex-row items-center justify-between w-full max-w-4xl mx-auto py-10 relative">
      {/* Connector Line */}
      <div className="absolute top-[40px] md:top-[34px] left-10 right-10 h-[2px] bg-white/5 hidden md:block">
        <motion.div 
          className="h-full bg-hud-accent shadow-[0_0_10px_#60A5FA]"
          initial={{ width: 0 }}
          animate={{ width: `${(activeIndex / (states.length - 1)) * 100}%` }}
          transition={{ duration: 1, ease: "easeInOut" }}
        />
      </div>

      {states.map((state, i) => {
        const isActive = i <= activeIndex;
        const isCurrent = i === activeIndex;

        return (
          <div key={state.id} className="flex flex-col items-center relative z-10 mb-8 md:mb-0">
            <motion.div
              animate={{
                scale: isCurrent ? 1.1 : 1,
                borderColor: isActive ? "rgba(96, 165, 250, 0.5)" : "rgba(255, 255, 255, 0.1)",
                boxShadow: isCurrent ? "0 0 20px rgba(96, 165, 250, 0.2)" : "none",
              }}
              className={cn(
                "h-16 w-16 rounded-2xl flex items-center justify-center glass-panel border-2 transition-all duration-500 bg-hud-bg",
                isActive ? "text-hud-accent" : "text-white/20"
              )}
            >
              <state.icon size={28} />
              
              {/* Active Pulse */}
              {isCurrent && (
                <motion.div
                  className="absolute inset-0 rounded-2xl bg-hud-accent/20"
                  animate={{ scale: [1, 1.2, 1], opacity: [0.5, 0, 0.5] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              )}
            </motion.div>

            <motion.div 
              className="mt-4 text-center"
              animate={{ opacity: isActive ? 1 : 0.3 }}
            >
              <p className="text-[10px] font-mono tracking-widest uppercase text-hud-accent mb-1">{state.name}</p>
              <p className="text-[8px] font-mono tracking-tighter uppercase text-white/40">{state.role}</p>
            </motion.div>
          </div>
        );
      })}
    </div>
  );
}
