"use client";

import { motion } from "framer-motion";
import { HUDCard } from "@/components/hud/HUDCard";
import { HUDStatus } from "@/components/hud/HUDControls";
import { Brain, Code, ShieldCheck, Zap } from "lucide-react";

const agents = [
  {
    name: "Atlas",
    role: "Spec Architect",
    icon: Brain,
    desc: "Transforms raw PRDs into structured technical blueprints.",
    color: "text-blue-400",
  },
  {
    name: "Vector",
    role: "API Designer",
    icon: Zap,
    desc: "Engineers high-performance OpenAPI contracts.",
    color: "text-purple-400",
  },
  {
    name: "Core",
    role: "Logic Engineer",
    icon: Code,
    desc: "Implements robust, production-ready backend logic.",
    color: "text-green-400",
  },
  {
    name: "Guard",
    role: "QA Specialist",
    icon: ShieldCheck,
    desc: "Enforces quality through rigorous test generation.",
    color: "text-red-400",
  },
];

export function AgentGrid() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {agents.map((agent, i) => (
        <HUDCard key={agent.name} title={agent.name} delay={i * 0.1}>
          <div className="flex flex-col space-y-4">
            <div className="flex items-start justify-between">
              <div className="p-2 bg-white/5 rounded-lg border border-white/10">
                <agent.icon className={`h-5 w-5 ${agent.color}`} />
              </div>
              <HUDStatus status="active" label="Online" />
            </div>
            
            <div>
              <p className="text-[10px] uppercase font-mono tracking-widest text-white/40 mb-1">
                {agent.role}
              </p>
              <p className="text-xs text-white/70 leading-relaxed font-sans">
                {agent.desc}
              </p>
            </div>

            <div className="pt-2 flex justify-between items-center border-t border-white/5">
              <span className="text-[10px] font-mono text-white/30 uppercase">Uptime 99.9%</span>
              <div className="flex space-x-1">
                {[...Array(5)].map((_, j) => (
                  <motion.div
                    key={j}
                    animate={{ opacity: [0.3, 1, 0.3] }}
                    transition={{ duration: 2, repeat: Infinity, delay: j * 0.2 }}
                    className="h-1 w-2 bg-hud-accent/40 rounded-sm"
                  />
                ))}
              </div>
            </div>
          </div>
        </HUDCard>
      ))}
    </div>
  );
}
