"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface HUDButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger";
  size?: "sm" | "md" | "lg";
  glow?: boolean;
}

export function HUDButton({ 
  children, 
  variant = "primary", 
  size = "md", 
  glow = false, 
  className, 
  ...props 
}: HUDButtonProps) {
  const variants = {
    primary: "bg-hud-accent/10 border-hud-accent/20 hover:bg-hud-accent/20 text-hud-accent",
    secondary: "bg-white/5 border-white/10 hover:bg-white/10 text-white/70",
    danger: "bg-red-500/10 border-red-500/20 hover:bg-red-500/20 text-red-400",
  };

  const sizes = {
    sm: "px-2 py-1 text-[10px]",
    md: "px-4 py-2 text-xs",
    lg: "px-6 py-3 text-sm",
  };

  return (
    <motion.button
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      className={cn(
        "relative uppercase tracking-widest font-mono border transition-all duration-200",
        variants[variant],
        sizes[size],
        glow && "shadow-[0_0_15px_rgba(96,165,250,0.3)]",
        className
      )}
      {...props}
    >
      <span className="relative z-10">{children}</span>
      
      {/* HUD Accent Dots */}
      <div className="absolute top-0 left-0 h-1 w-1 bg-hud-accent/30" />
      <div className="absolute bottom-0 right-0 h-1 w-1 bg-hud-accent/30" />
    </motion.button>
  );
}

interface HUDStatusProps {
  status: "active" | "idle" | "error" | "complete";
  label?: string;
}

export function HUDStatus({ status, label }: HUDStatusProps) {
  const configs = {
    active: { color: "bg-hud-accent", glow: "shadow-[0_0_10px_#60A5FA]" },
    idle: { color: "bg-white/20", glow: "" },
    error: { color: "bg-red-500", glow: "shadow-[0_0_10px_#EF4444]" },
    complete: { color: "bg-green-500", glow: "shadow-[0_0_10px_#22C55E]" },
  };

  const config = configs[status];

  return (
    <div className="flex items-center space-x-2">
      <div className={cn("h-2 w-2 rounded-full", config.color, config.glow)} />
      {label && <span className="text-[10px] uppercase tracking-tighter text-white/40">{label}</span>}
    </div>
  );
}
