"use client";

import { ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface HUDCardProps {
  children: ReactNode;
  title?: string;
  className?: string;
  glow?: boolean;
  delay?: number;
}

export function HUDCard({ children, title, className, glow = false, delay = 0 }: HUDCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      className={cn(
        "glass-panel relative flex flex-col p-4 overflow-hidden",
        glow && "glass-panel-glow border-hud-accent/20",
        className
      )}
    >
      {/* HUD Header Bar */}
      {title && (
        <div className="mb-4 flex items-center justify-between border-b border-white/5 pb-2">
          <h3 className="text-xs font-mono uppercase tracking-[0.2em] text-white/50">
            <span className="mr-2 text-hud-accent">·</span>
            {title}
          </h3>
          <div className="flex space-x-1">
            <div className="h-1 w-1 rounded-full bg-white/10" />
            <div className="h-1 w-1 rounded-full bg-white/10" />
            <div className="h-1 w-1 rounded-full bg-hud-accent" />
          </div>
        </div>
      )}

      {/* Subtle HUD Micro-accents in corners */}
      <div className="absolute top-1 left-1 h-2 w-2 border-t border-l border-white/10" />
      <div className="absolute top-1 right-1 h-2 w-2 border-t border-r border-white/10" />
      <div className="absolute bottom-1 left-1 h-2 w-2 border-b border-l border-white/10" />
      <div className="absolute bottom-1 right-1 h-2 w-2 border-b border-r border-white/10" />

      {/* Inner Glow Pulse (if glow is on) */}
      {glow && (
        <div className="absolute -top-10 -right-10 h-32 w-32 bg-hud-accent/10 blur-[40px] pointer-events-none" />
      )}

      <div className="relative z-10 flex-1">{children}</div>
    </motion.div>
  );
}
