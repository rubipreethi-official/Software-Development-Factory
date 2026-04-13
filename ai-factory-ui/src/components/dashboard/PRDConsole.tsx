"use client";

import { useState } from "react";
import { HUDCard } from "@/components/hud/HUDCard";
import { HUDButton } from "@/components/hud/HUDControls";
import { Terminal } from "lucide-react";

export function PRDConsole({ onSubmit }: { onSubmit: (title: string, content: string) => void }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const loadSample = () => {
    setTitle("USER_AUTH_SERVICE_V1");
    setContent(`Create a robust user authentication and management service.
Requirements:
1. User registration with email/password and profile fields (name, bio).
2. JWT-based login and session management.
3. Password reset functionality with email verification.
4. User role management (Admin, User).
5. Profile update endpoints for users to manage their info.
6. Admin dashboard API to list and manage all users.
All endpoints should follow RESTful conventions and include proper validation.`);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (title && content) {
      onSubmit(title, content);
      setTitle("");
      setContent("");
    }
  };

  return (
    <HUDCard title="Input Console" glow delay={0.2}>
      <form onSubmit={handleSubmit} className="flex flex-col space-y-4">
        <div className="flex items-center space-x-2 text-hud-accent/50 mb-2">
          <Terminal size={14} />
          <span className="text-[10px] font-mono tracking-widest uppercase">System Intake Ready_</span>
        </div>
        
        <div className="space-y-2">
          <div className="flex justify-between items-center px-1">
            <label className="text-[10px] uppercase font-mono tracking-widest text-white/30">Project Title</label>
            <button 
              type="button" 
              onClick={loadSample}
              className="text-[9px] font-mono text-hud-accent/60 hover:text-hud-accent transition-colors uppercase tracking-widest border border-hud-accent/20 px-2 py-0.5 rounded-sm"
            >
              [Load Sample]
            </button>
          </div>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. AUTH_SYSTEM_V2"
            className="w-full bg-white/5 border border-white/10 p-3 text-sm focus:outline-none focus:border-hud-accent/50 transition-colors font-mono"
            required
          />
        </div>

        <div className="space-y-2">
          <label className="text-[10px] uppercase font-mono tracking-widest text-white/30 ml-1">Product Requirements</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="ENTER_DETAILED_REQUIREMENTS_HERE..."
            rows={8}
            className="w-full bg-white/5 border border-white/10 p-3 text-sm focus:outline-none focus:border-hud-accent/50 transition-colors font-sans resize-none"
            required
          />
        </div>

        <div className="flex justify-between items-center pt-2">
          <span className="text-[10px] font-mono text-white/20">WORD_COUNT: {content.split(/\s+/).filter(Boolean).length}</span>
          <HUDButton type="submit" variant="primary" glow size="lg">
            EXECUTE_WORKFLOW
          </HUDButton>
        </div>
      </form>
    </HUDCard>
  );
}
